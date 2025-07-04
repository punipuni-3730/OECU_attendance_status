from playwright.sync_api import sync_playwright, TimeoutError
import json
import os
from datetime import datetime
import unicodedata

# セッション保存用のファイル
SESSION_FILE = "session.json"

def get_display_width(text):
    """テキストの表示幅を計算（全角=2、半角=1）"""
    width = 0
    for char in text:
        if unicodedata.east_asian_width(char) in ('F', 'W'):
            width += 2  # 全角文字
        else:
            width += 1  # 半角文字
    return width

def to_fullwidth_number(text):
    """半角数字を全角数字に変換"""
    halfwidth_to_fullwidth = str.maketrans('0123456789', '０１２３４５６７８９')
    return text.translate(halfwidth_to_fullwidth)

def get_current_semester():
    """現在の日付に基づいて学期を判定"""
    current_date = datetime.now()
    month = current_date.month
    year = current_date.year
    
    if 4 <= month <= 8:
        return f"{year}年度前期"
    else:
        return f"{year}年度後期"

def get_subject_list(page):
    """授業一覧から対象の授業を取得"""
    current_semester = get_current_semester()
    print(f"🎓 対象学期: {current_semester}")
    
    try:
        subject_data = page.evaluate(f"""
            () => {{
                const results = [];
                const rows = document.querySelectorAll("table.main_table tbody tr");
                
                rows.forEach((row, index) => {{
                    const semesterCell = row.querySelector("td.hide_xs");
                    const subjectCell = row.querySelector("td.mb_disp");
                    const button = row.querySelector("button[id*='form-list-']");
                    
                    if (semesterCell && subjectCell && button) {{
                        const semester = semesterCell.textContent.trim();
                        const subject = subjectCell.textContent.trim();
                        const buttonId = button.id;
                        
                        // 曜日と時限の情報を取得
                        const cells = row.querySelectorAll("td");
                        let dayAndPeriod = "";
                        
                        // テーブルの構造を確認して曜日・時限を取得
                        let day = "";
                        let period = "";
                        
                        for (let i = 0; i < cells.length; i++) {{
                            const cellText = cells[i].textContent.trim();
                            
                            // 曜日のパターンをチェック（月曜日、火曜日、水曜日、木曜日、金曜日、土曜日、日曜日）
                            if (cellText.match(/^[月火水木金土日]曜日$/)) {{
                                day = cellText.replace("曜日", "");
                            }}
                            
                            // 時限のパターンをチェック（1時限、2時限、3時限...）
                            if (cellText.match(/^[0-9]+時限$/)) {{
                                period = cellText.replace("時限", "");
                            }}
                        }}
                        
                        // 曜日と時限が両方取得できた場合に結合
                        if (day && period) {{
                            dayAndPeriod = day + period;
                        }}
                        
                        if (semester === "{current_semester}") {{
                            results.push({{
                                semester: semester,
                                subject: subject,
                                buttonId: buttonId,
                                dayAndPeriod: dayAndPeriod,
                                index: index
                            }});
                        }}
                    }}
                }});
                
                return results;
            }}
        """)
        
        # 曜日と時限でソート（Python側で処理）
        def sort_by_day_and_period(item):
            day_order = {'月': 1, '火': 2, '水': 3, '木': 4, '金': 5, '土': 6, '日': 7}
            day_and_period = item.get('dayAndPeriod', '')
            
            if not day_and_period:
                return (999, 999)  # 曜日・時限がない場合は最後に表示
            
            day = day_and_period[0]
            try:
                period = int(day_and_period[1:])
            except ValueError:
                return (999, 999)
            
            return (day_order.get(day, 999), period)
        
        subject_data.sort(key=sort_by_day_and_period)
        
        print(f"📚 {current_semester}の授業を{len(subject_data)}件見つけました:")
        for i, subject in enumerate(subject_data):
            day_period = subject.get('dayAndPeriod', '')
            if day_period:
                print(f"  {i+1}. {day_period} {subject['subject']}")
            else:
                print(f"  {i+1}. {subject['subject']}")
        
        return subject_data
    except Exception as e:
        print(f"❌ 授業一覧の取得中にエラーが発生しました: {str(e)}")
        return []

def get_attendance_for_subject_by_click(page, context, subject_info, subject_index):
    """クリックして授業ページを開き、出席情報を取得"""
    
    try:
        # 授業のボタンをクリック
        click_result = page.evaluate(f"""
            () => {{
                const button = document.getElementById('{subject_info['buttonId']}');
                if (button) {{
                    button.click();
                    return true;
                }} else {{
                    console.log('Button not found: {subject_info['buttonId']}');
                    return false;
                }}
            }}
        """)
        
        if not click_result:
            print(f"❌ ボタンが見つかりませんでした")
            return None
        
        # ページ遷移を待つ
        try:
            page.wait_for_load_state("networkidle", timeout=8000)  # 15秒→8秒に短縮
        except TimeoutError:
            print(f"⚠️ ページ遷移でタイムアウト")
        
        # 出席情報要素が読み込まれるまで待機
        try:
            page.wait_for_selector("div.contents_state", timeout=5000)  # 10秒→5秒に短縮
        except TimeoutError:
            print(f"⚠️ 出席情報要素の読み込みでタイムアウト")
        
        # 最小限の待機（500ms→200msに短縮）
        page.wait_for_timeout(200)
        
        # 出席情報を取得
        attendance_data = page.evaluate("""
            () => {
                const results = [];
                const elements = document.querySelectorAll("div.contents_state");
                
                elements.forEach((el, index) => {
                    const lessonNumberEl = el.querySelector("div.contents_name");
                    if (!lessonNumberEl) return;
                    
                    const lessonNumber = lessonNumberEl.textContent.trim();
                    const img = el.querySelector("img");
                    let status = "―";
                    
                    if (img && img.getAttribute("title")) {
                        status = img.getAttribute("title");
                    } else {
                        // 画像がない場合は「―」の可能性があるかチェック
                        const divs = el.querySelectorAll("div");
                        for (let div of divs) {
                            if (div.textContent && div.textContent.includes("―")) {
                                status = "―";
                                break;
                            }
                        }
                    }
                    
                    results.push({ lesson: lessonNumber, status: status });
                });
                
                return results;
            }
        """)
        
        print(f"✅ {len(attendance_data)}件取得")
        
        if len(attendance_data) == 0:
            print(f"⚠️ 出席情報が見つかりませんでした")
            return None
        
        # 出席状況の集計（未実施はカウントしない）
        current_semester = get_current_semester()
        is_second_semester = "後期" in current_semester
        
        # 通年授業の場合、前期/後期で集計対象を分ける
        target_attendance_data = attendance_data
        if len(attendance_data) > 13:  # 通年授業の場合
            if is_second_semester:
                # 後期の場合、14-26回のみを集計対象とする
                target_attendance_data = [data for data in attendance_data if int(data['lesson']) >= 14]
            else:
                # 前期の場合、1-13回のみを集計対象とする
                target_attendance_data = [data for data in attendance_data if int(data['lesson']) <= 13]
        
        attendance_count = sum(1 for data in target_attendance_data if data['status'] == '出席')
        absence_count = sum(1 for data in target_attendance_data if data['status'] == '欠席')
        implemented_count = attendance_count + absence_count  # 実施された授業数
        
        print(f"📈 出席{attendance_count}, 欠席{absence_count}, 実施{implemented_count}")
        
        return {
            'subject': subject_info['subject'],
            'dayAndPeriod': subject_info.get('dayAndPeriod', ''),
            'attendance_data': attendance_data,
            'attendance_count': attendance_count,
            'absence_count': absence_count,
            'implemented_count': implemented_count,  # 未実施の代わりに実施数
            'total_count': len(target_attendance_data)  # 表示対象の総回数
        }
        
    except Exception as e:
        print(f"❌ エラー: {str(e)}")
        return None

def wait_for_new_page(context, timeout=5000):  # 10秒→5秒に短縮
    """新しいタブが開くのを待つ。なければ現在のページを返す."""
    try:
        new_page = context.wait_for_event("page", timeout=timeout)
        print("🔄 新しいタブを検出しました。")
        new_page.wait_for_load_state("networkidle", timeout=5000)  # 10秒→5秒に短縮
        return new_page
    except TimeoutError:
        print("🔄 新しいタブは検出されませんでした。現在のページを使用します。")
        return context.pages[-1]

def save_session(context):
    """セッションクッキーを保存"""
    storage_state = context.storage_state()
    with open(SESSION_FILE, "w") as f:
        json.dump(storage_state, f)
    print("✅ セッションを保存しました: session.json")

def load_session(context):
    """セッションクッキーを復元"""
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r") as f:
            storage_state = json.load(f)
        context.add_cookies(storage_state["cookies"])
        print("✅ セッションを復元しました: session.json")
        return True
    return False

# メイン処理の開始
print("🚀 出席情報取得スクリプトを開始しました")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    # 1. セッションの復元を試みる
    session_restored = load_session(context)

    # 2. ポータルログインページにアクセス
    if not session_restored:
        print("📄 ログインページに移動中...")
        page.goto("https://myportal.osakac.ac.jp/")
        page.wait_for_load_state("networkidle")
        print("✅ ログインページの読み込み完了")
        print("🔐 Googleログインをブラウザで完了してください。")
        print("👉 「トップ画面へ」ボタンをクリックして、トップページ(https://myportal.osakac.ac.jp/m/mycontent/list.xhtml)に移動したら Enter を押してください。")
        input()
        save_session(context)
        
        # ログイン後のページ読み込みを待機
        try:
            page.wait_for_load_state("networkidle", timeout=8000)  # 15秒→8秒に短縮
            print("✅ ログイン後のページ読み込み完了")
        except TimeoutError:
            print("⚠️ ログイン後のページ読み込みでタイムアウトしました。続行します...")
    else:
        try:
            print("📄 授業一覧ページに移動中...")
            page.goto("https://myportal.osakac.ac.jp/m/mycontent/list.xhtml", wait_until="networkidle")
            page.wait_for_load_state("networkidle", timeout=8000)  # 15秒→8秒に短縮
            print("✅ 授業一覧ページの読み込み完了")
        except TimeoutError:
            print("⚠️ 授業一覧ページの読み込みでタイムアウトしました。続行します...")
        
        # ページの内容が完全に読み込まれるまで待機
        try:
            page.wait_for_selector("table.main_table", timeout=5000)  # 10秒→5秒に短縮
            print("✅ 授業一覧テーブルの読み込み完了")
        except TimeoutError:
            print("⚠️ 授業一覧テーブルの読み込みでタイムアウトしました。続行します...")

    # 3. 新しいタブが開いていたら切り替え
    page = wait_for_new_page(context)

    # 4. 授業一覧を取得
    subject_list = get_subject_list(page)
    
    if not subject_list:
        print("❌ 授業一覧が取得できませんでした")
        browser.close()
        exit()
    
    # 5. 全ての授業の出席情報を取得（クリック方式）
    print(f"\n🚀 {len(subject_list)}件の授業の出席情報を取得中...")
    
    all_attendance_data = []
    
    # 各授業の情報に総数を追加
    for subject_info in subject_list:
        subject_info['total'] = len(subject_list)
    
    # 全ての授業の出席情報を取得（クリック→取得→戻る）
    success_count = 0
    for i, subject_info in enumerate(subject_list):
        print(f"\n🔄 [{i+1}/{len(subject_list)}] {subject_info['subject']} を処理中...")
        
        # 授業をクリックして出席情報を取得
        attendance_result = get_attendance_for_subject_by_click(page, context, subject_info, i)
        
        if attendance_result:
            all_attendance_data.append(attendance_result)
            success_count += 1
            print(f"✅ [{i+1}/{len(subject_list)}] 完了")
        else:
            print(f"❌ [{i+1}/{len(subject_list)}] 失敗")
        
        # 授業一覧ページに戻る（最後の授業でない場合）
        if i < len(subject_list) - 1:
            print(f"🔄 授業一覧に戻り中...")
            try:
                page.goto("https://myportal.osakac.ac.jp/m/mycontent/list.xhtml", wait_until="networkidle")
                page.wait_for_load_state("networkidle", timeout=8000)  # 15秒→8秒に短縮
                
                # 授業一覧テーブルが読み込まれるまで待機
                page.wait_for_selector("table.main_table", timeout=5000)  # 10秒→5秒に短縮
                
                # 次の授業取得まで最小限の待機（500ms→200msに短縮）
                page.wait_for_timeout(200)
                
            except TimeoutError:
                print(f"⚠️ [{subject_info['subject']}] 授業一覧ページに戻る際にタイムアウトしました。続行します...")
            except Exception as e:
                print(f"⚠️ [{subject_info['subject']}] 授業一覧ページに戻る際にエラーが発生しました: {str(e)}。続行します...")
    
    # 6. 結果を表示
    if all_attendance_data:
        # 出席情報も曜日・時限で並び替え
        def sort_attendance_by_day_and_period(item):
            day_order = {'月': 1, '火': 2, '水': 3, '木': 4, '金': 5, '土': 6, '日': 7}
            day_and_period = item.get('dayAndPeriod', '')
            
            # 4月でない場合、すべて未実施の授業は最後に表示
            current_date = datetime.now()
            if current_date.month != 4:
                all_unimplemented = all(attendance['status'] == '―' for attendance in item.get('attendance_data', []))
                if all_unimplemented:
                    return (9999, 9999)  # 最後に表示
            
            if not day_and_period:
                return (999, 999)  # 曜日・時限がない場合は最後に表示
            
            day = day_and_period[0]
            try:
                period = int(day_and_period[1:])
            except ValueError:
                return (999, 999)
            
            return (day_order.get(day, 999), period)
        
        all_attendance_data.sort(key=sort_attendance_by_day_and_period)
        
        print("\n" + "="*100)
        print(f"📊 全授業の出席情報 ({success_count}/{len(subject_list)}件取得成功)")
        print("="*100)
        
        # 最大授業回数を取得してヘッダーを作成（最大13回まで表示）
        max_lessons = max(len(data['attendance_data']) for data in all_attendance_data) if all_attendance_data else 0
        
        # 通年授業（26回）の場合、前期/後期で分けて表示
        current_semester = get_current_semester()
        is_second_semester = "後期" in current_semester
        
        if max_lessons > 13:
            max_lessons = 13  # 表示は13回まで
        else:
            max_lessons = min(max_lessons, 13)
        
        # 授業名の最大長を計算（曜日・時限も含めて）
        max_subject_name_length = 0
        for data in all_attendance_data:
            if data.get('dayAndPeriod'):
                # 授業名が15文字以上の場合は省略
                subject_name = data['subject']
                if len(subject_name) > 15:
                    subject_name = subject_name[:15] + "..."
                display_name = f"{data['dayAndPeriod']} {subject_name}"
            else:
                # 授業名が15文字以上の場合は省略
                subject_name = data['subject']
                if len(subject_name) > 15:
                    subject_name = subject_name[:15] + "..."
                display_name = subject_name
            max_subject_name_length = max(max_subject_name_length, len(display_name))
        
        # 固定で15文字に設定（出席状況は17字目から表示）
        max_subject_name_length = 15
        
        # ヘッダー行を作成
        # 「授業名」を15文字幅で正確に配置
        header_title = "授業名"
        header_width = get_display_width(header_title)
        target_width = 30  # 15文字 = 30半角文字分の幅
        padding_needed = target_width - header_width
        header = header_title + " " * max(0, padding_needed)
        header += "　"  # 16字目に全角スペースを追加（全角換算で17字目から開始）
        for i in range(1, max_lessons + 1):
            header += f"{i:>3}"
        header += " 出席 欠席 実施 合計"
        print(header)
        print("-" * 100)
        
        # 各授業の出席状況を表示
        for data in all_attendance_data:
            # 曜日・時限と授業名を組み合わせて表示
            if data.get('dayAndPeriod'):
                # 曜日・時限は3文字固定、残り12文字で授業名を表示
                day_period = data['dayAndPeriod']  # 例：「月1」
                subject_name = data['subject']
                
                # 授業名の表示可能文字数を計算（12文字分の幅）
                available_width = 24  # 12文字 = 24半角文字分の幅
                
                # 文字を1文字ずつ追加して幅を計算
                truncated_name = ""
                current_width = 0
                for char in subject_name:
                    char_width = get_display_width(char)
                    if current_width + char_width <= available_width - 6:  # "..."分を考慮
                        truncated_name += char
                        current_width += char_width
                    else:
                        if truncated_name:  # 文字が切り詰められた場合
                            truncated_name += "..."
                        break
                else:
                    # 全部入った場合は何もしない
                    truncated_name = subject_name
                
                # 曜日・時限 + スペース + 授業名の形式
                display_name = f"{day_period} {truncated_name}"
            else:
                # 曜日・時限がない場合は15文字すべてを授業名に使用
                subject_name = data['subject']
                
                # 15文字分の幅で授業名を調整
                available_width = 30  # 15文字 = 30半角文字分の幅
                
                # 文字を1文字ずつ追加して幅を計算
                truncated_name = ""
                current_width = 0
                for char in subject_name:
                    char_width = get_display_width(char)
                    if current_width + char_width <= available_width - 6:  # "..."分を考慮
                        truncated_name += char
                        current_width += char_width
                    else:
                        if truncated_name:  # 文字が切り詰められた場合
                            truncated_name += "..."
                        break
                else:
                    # 全部入った場合は何もしない
                    truncated_name = subject_name
                
                display_name = truncated_name
            
            # 授業名を15文字ちょうどに調整（全角文字を考慮した固定幅）
            display_width = get_display_width(display_name)
            
            # 15文字分の表示幅にするため、不足分をスペースで埋める
            target_width = 30  # 15文字 = 30半角文字分の幅
            padding_needed = target_width - display_width
            row = display_name + " " * max(0, padding_needed)
            
            # 16字目に全角スペースを追加（全角換算で17字目から出席状況開始）
            row += "　"
            
            # 出席状況をマッピング
            status_map = {}
            for attendance in data['attendance_data']:
                lesson_num = int(attendance['lesson'])
                status = attendance['status']
                
                # 通年授業の場合、前期/後期で表示する回数を調整
                display_lesson_num = lesson_num
                if len(data['attendance_data']) > 13:  # 通年授業の場合
                    if is_second_semester:
                        # 後期の場合、14-26回を1-13回として表示
                        if lesson_num >= 14:
                            display_lesson_num = lesson_num - 13
                        else:
                            continue  # 前期の回数はスキップ
                    else:
                        # 前期の場合、1-13回のみ表示
                        if lesson_num > 13:
                            continue  # 後期の回数はスキップ
                
                # 表示範囲内の場合のみマッピングに追加
                if 1 <= display_lesson_num <= 13:
                    # 状態を記号に変換
                    if status == '出席':
                        symbol = '○'
                    elif status == '欠席':
                        symbol = '✕'
                    else:
                        symbol = '―'
                    status_map[str(display_lesson_num)] = symbol
            
            # 各回の出席状況を表示
            for i in range(1, max_lessons + 1):
                lesson_key = str(i)  # 授業回数は文字列として保存されている
                if lesson_key in status_map:
                    row += f"{status_map[lesson_key]:>3}"
                else:
                    row += "   "  # 該当回がない場合は空白
            
            # 集計情報を追加（未実施は除外）
            implemented_count = data['attendance_count'] + data['absence_count']  # 実施回数 = 出席 + 欠席
            row += f" {data['attendance_count']:>4} {data['absence_count']:>4} {implemented_count:>4} {data['total_count']:>4}"
            print(row)
        
        print("-" * 100)
        
        # 全体の統計情報を表示
        total_attendance = sum(data['attendance_count'] for data in all_attendance_data)
        total_absence = sum(data['absence_count'] for data in all_attendance_data)
        total_implemented = total_attendance + total_absence  # 実施回数 = 出席 + 欠席
        total_lessons = sum(data['total_count'] for data in all_attendance_data)
        
        print("\n" + "="*50)
        print("📈 全体統計")
        print("="*50)
        print(f"総出席回数: {total_attendance}回")
        print(f"総欠席回数: {total_absence}回")
        print(f"総実施回数: {total_implemented}回")
        print(f"総授業回数: {total_lessons}回")
        if total_implemented > 0:
            attendance_rate = (total_attendance / total_implemented) * 100
            print(f"出席率: {attendance_rate:.1f}%")
        
        print("\n凡例: ○=出席, ✕=欠席, ―=未実施")
    else:
        print("❌ 出席情報を取得できませんでした")
    
    # 7. ブラウザを閉じる
    browser.close()

print("\n✅ 処理完了!")
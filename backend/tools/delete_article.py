#!/usr/bin/env python3
"""
Інструмент видалення статей для GradusMedia
Безпечне видалення контенту з бази даних з підтвердженням
"""
import os
import sys
from datetime import datetime, timedelta
from typing import Optional, List

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = os.getenv('NEON_DATABASE_URL') or os.getenv('DATABASE_URL')

class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text.center(60)}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}\n")


def print_success(text: str):
    print(f"{Colors.GREEN}✅ {text}{Colors.END}")


def print_warning(text: str):
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.END}")


def print_error(text: str):
    print(f"{Colors.RED}❌ {text}{Colors.END}")


def print_info(text: str):
    print(f"{Colors.BLUE}ℹ️  {text}{Colors.END}")


def get_platform_icons(status: str, platforms: list) -> str:
    icons = []
    if status in ['approved', 'posted']:
        icons.append("🌐")
    if platforms:
        if 'facebook' in platforms:
            icons.append("📱 FB")
        if 'linkedin' in platforms:
            icons.append("💼 LI")
        if 'telegram' in platforms:
            icons.append("✈️ TG")
    return " ".join(icons) if icons else "—"


def list_recent_articles(limit: int = 20, status_filter: Optional[str] = None):
    """Показати останні статті"""
    print_header("📋 ОСТАННІ СТАТТІ")
    
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        query = """
            SELECT id, source_title, translated_title, status, platforms, 
                   created_at, posted_at, source, category
            FROM content_queue 
            WHERE 1=1
        """
        params = []
        
        if status_filter:
            query += " AND status = %s"
            params.append(status_filter)
        
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        
        cur.execute(query, params)
        articles = cur.fetchall()
        
        if not articles:
            print_warning("Статті не знайдено")
            return
        
        print(f"{'ID':<6} {'Заголовок':<40} {'Статус':<12} {'Платформи':<15} {'Дата':<12}")
        print("-" * 90)
        
        for art in articles:
            title = (art['translated_title'] or art['source_title'] or 'Без назви')[:38]
            status = art['status'] or 'pending'
            platforms = art['platforms'] or []
            date = art['created_at'].strftime('%d.%m.%Y') if art['created_at'] else '—'
            icons = get_platform_icons(status, platforms)
            
            status_color = Colors.GREEN if status == 'posted' else Colors.YELLOW if status == 'approved' else Colors.END
            print(f"{art['id']:<6} {title:<40} {status_color}{status:<12}{Colors.END} {icons:<15} {date:<12}")
        
        print(f"\n{Colors.CYAN}Всього: {len(articles)} статей{Colors.END}")
        
    finally:
        conn.close()


def search_articles(keyword: str):
    """Пошук статей за ключовим словом"""
    print_header(f"🔍 ПОШУК: {keyword}")
    
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, source_title, translated_title, status, platforms, created_at, source
            FROM content_queue 
            WHERE source_title ILIKE %s 
               OR translated_title ILIKE %s 
               OR original_text ILIKE %s
               OR translated_text ILIKE %s
            ORDER BY created_at DESC
            LIMIT 50
        """, (f'%{keyword}%', f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'))
        
        articles = cur.fetchall()
        
        if not articles:
            print_warning(f"Статті за запитом '{keyword}' не знайдено")
            return
        
        print(f"{'ID':<6} {'Заголовок':<45} {'Статус':<12} {'Джерело':<20}")
        print("-" * 90)
        
        for art in articles:
            title = (art['translated_title'] or art['source_title'] or 'Без назви')[:43]
            status = art['status'] or 'pending'
            source = (art['source'] or '—')[:18]
            
            print(f"{art['id']:<6} {title:<45} {status:<12} {source:<20}")
        
        print(f"\n{Colors.CYAN}Знайдено: {len(articles)} статей{Colors.END}")
        
    finally:
        conn.close()


def show_article_details(article_id: int) -> Optional[dict]:
    """Показати деталі статті"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        cur.execute("""
            SELECT * FROM content_queue WHERE id = %s
        """, (article_id,))
        
        article = cur.fetchone()
        
        if not article:
            print_error(f"Стаття з ID {article_id} не знайдена")
            return None
        
        cur.execute("""
            SELECT COUNT(*) as count FROM approval_log WHERE content_id = %s
        """, (article_id,))
        
        log_count = cur.fetchone()['count']
        
        print_header(f"📄 ДЕТАЛІ СТАТТІ #{article_id}")
        
        title = article['translated_title'] or article['source_title'] or 'Без назви'
        print(f"{Colors.BOLD}Заголовок:{Colors.END} {title}")
        print(f"{Colors.BOLD}Джерело:{Colors.END} {article['source'] or '—'}")
        print(f"{Colors.BOLD}Статус:{Colors.END} {article['status'] or 'pending'}")
        print(f"{Colors.BOLD}Категорія:{Colors.END} {article['category'] or '—'}")
        print(f"{Colors.BOLD}Платформи:{Colors.END} {', '.join(article['platforms'] or []) or '—'}")
        print(f"{Colors.BOLD}Створено:{Colors.END} {article['created_at']}")
        print(f"{Colors.BOLD}Опубліковано:{Colors.END} {article['posted_at'] or '—'}")
        print(f"{Colors.BOLD}URL джерела:{Colors.END} {article['source_url'] or '—'}")
        
        print(f"\n{Colors.YELLOW}📊 Пов'язані записи:{Colors.END}")
        print(f"   • approval_log: {log_count} записів")
        
        has_image = bool(article.get('image_data') or article.get('local_image_path') or article.get('image_url'))
        print(f"   • Зображення: {'✅ Є' if has_image else '❌ Немає'}")
        
        return dict(article), log_count
        
    finally:
        conn.close()


def delete_article(article_id: int, dry_run: bool = False):
    """Видалити статтю за ID"""
    result = show_article_details(article_id)
    
    if not result:
        return False
    
    article, log_count = result
    
    print(f"\n{Colors.RED}{Colors.BOLD}⚠️  УВАГА: Ви збираєтесь видалити:{Colors.END}")
    print(f"   • 1 статтю (ID: {article_id})")
    print(f"   • {log_count} записів в approval_log")
    
    if dry_run:
        print_info("Режим dry-run: видалення НЕ буде виконано")
        return True
    
    confirm = input(f"\n{Colors.YELLOW}Введіть 'yes' для підтвердження видалення: {Colors.END}").strip().lower()
    
    if confirm != 'yes':
        print_warning("Видалення скасовано")
        return False
    
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        cur.execute("DELETE FROM approval_log WHERE content_id = %s", (article_id,))
        deleted_logs = cur.rowcount
        
        cur.execute("DELETE FROM content_queue WHERE id = %s", (article_id,))
        deleted_articles = cur.rowcount
        
        conn.commit()
        
        print_success(f"Видалено: {deleted_articles} статтю, {deleted_logs} записів логів")
        
        log_deletion(article_id, article.get('translated_title') or article.get('source_title'))
        
        return True
        
    except Exception as e:
        conn.rollback()
        print_error(f"Помилка при видаленні: {e}")
        return False
        
    finally:
        conn.close()


def bulk_delete(article_ids: List[int], dry_run: bool = False):
    """Масове видалення статей"""
    print_header(f"🗑️ МАСОВЕ ВИДАЛЕННЯ ({len(article_ids)} статей)")
    
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, translated_title, source_title, status 
            FROM content_queue 
            WHERE id = ANY(%s)
        """, (article_ids,))
        
        articles = cur.fetchall()
        
        if not articles:
            print_error("Жодної статті не знайдено")
            return False
        
        print(f"\n{Colors.BOLD}Статті для видалення:{Colors.END}")
        for art in articles:
            title = (art['translated_title'] or art['source_title'] or 'Без назви')[:50]
            print(f"   • ID {art['id']}: {title}")
        
        found_ids = [art['id'] for art in articles]
        missing_ids = set(article_ids) - set(found_ids)
        if missing_ids:
            print_warning(f"Не знайдено ID: {missing_ids}")
        
        cur.execute("""
            SELECT COUNT(*) as count FROM approval_log WHERE content_id = ANY(%s)
        """, (found_ids,))
        log_count = cur.fetchone()['count']
        
        print(f"\n{Colors.RED}Буде видалено:{Colors.END}")
        print(f"   • {len(articles)} статей")
        print(f"   • {log_count} записів логів")
        
        if dry_run:
            print_info("Режим dry-run: видалення НЕ буде виконано")
            return True
        
        confirm = input(f"\n{Colors.YELLOW}Введіть 'yes' для підтвердження: {Colors.END}").strip().lower()
        
        if confirm != 'yes':
            print_warning("Видалення скасовано")
            return False
        
        cur.execute("DELETE FROM approval_log WHERE content_id = ANY(%s)", (found_ids,))
        cur.execute("DELETE FROM content_queue WHERE id = ANY(%s)", (found_ids,))
        
        conn.commit()
        
        print_success(f"Видалено {len(found_ids)} статей")
        return True
        
    except Exception as e:
        conn.rollback()
        print_error(f"Помилка: {e}")
        return False
        
    finally:
        conn.close()


def delete_by_date_range(start_date: str, end_date: str, status_filter: Optional[str] = None, dry_run: bool = False):
    """Видалити статті за діапазоном дат"""
    print_header(f"📅 ВИДАЛЕННЯ ЗА ДАТОЮ: {start_date} — {end_date}")
    
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
    except ValueError:
        print_error("Невірний формат дати. Використовуйте YYYY-MM-DD")
        return False
    
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        query = """
            SELECT id, translated_title, source_title, status, created_at
            FROM content_queue 
            WHERE created_at >= %s AND created_at < %s
        """
        params = [start, end]
        
        if status_filter:
            query += " AND status = %s"
            params.append(status_filter)
        
        query += " ORDER BY created_at"
        
        cur.execute(query, params)
        articles = cur.fetchall()
        
        if not articles:
            print_warning("Статті за цей період не знайдено")
            return False
        
        print(f"\n{Colors.BOLD}Знайдено {len(articles)} статей:{Colors.END}")
        for art in articles:
            title = (art['translated_title'] or art['source_title'] or 'Без назви')[:40]
            date = art['created_at'].strftime('%d.%m.%Y %H:%M')
            print(f"   • ID {art['id']}: {title} ({date})")
        
        if dry_run:
            print_info("Режим dry-run: видалення НЕ буде виконано")
            return True
        
        confirm = input(f"\n{Colors.YELLOW}Введіть 'yes' для видалення всіх {len(articles)} статей: {Colors.END}").strip().lower()
        
        if confirm != 'yes':
            print_warning("Видалення скасовано")
            return False
        
        article_ids = [art['id'] for art in articles]
        
        cur.execute("DELETE FROM approval_log WHERE content_id = ANY(%s)", (article_ids,))
        cur.execute("DELETE FROM content_queue WHERE id = ANY(%s)", (article_ids,))
        
        conn.commit()
        
        print_success(f"Видалено {len(article_ids)} статей")
        return True
        
    except Exception as e:
        conn.rollback()
        print_error(f"Помилка: {e}")
        return False
        
    finally:
        conn.close()


def log_deletion(article_id: int, title: str):
    """Логувати видалення"""
    log_file = os.path.join(os.path.dirname(__file__), 'deletion_log.txt')
    
    with open(log_file, 'a', encoding='utf-8') as f:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        f.write(f"{timestamp} | Deleted ID: {article_id} | Title: {title}\n")


def export_articles(filename: str = 'articles_export.txt'):
    """Експортувати список статей у файл"""
    print_header("📤 ЕКСПОРТ СТАТЕЙ")
    
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, source_title, translated_title, status, source, created_at
            FROM content_queue 
            ORDER BY created_at DESC
        """)
        
        articles = cur.fetchall()
        
        filepath = os.path.join(os.path.dirname(__file__), filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"Експорт статей GradusMedia — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
            
            for art in articles:
                title = art['translated_title'] or art['source_title'] or 'Без назви'
                f.write(f"ID: {art['id']}\n")
                f.write(f"Заголовок: {title}\n")
                f.write(f"Статус: {art['status']}\n")
                f.write(f"Джерело: {art['source']}\n")
                f.write(f"Дата: {art['created_at']}\n")
                f.write("-" * 40 + "\n")
        
        print_success(f"Експортовано {len(articles)} статей до {filepath}")
        
    finally:
        conn.close()


def show_menu():
    """Головне меню"""
    print_header("🗑️ ІНСТРУМЕНТ ВИДАЛЕННЯ СТАТЕЙ")
    
    print(f"""
{Colors.BOLD}Оберіть дію:{Colors.END}

  1. 📋 Показати останні статті
  2. 🔍 Пошук статей
  3. 📄 Деталі статті (за ID)
  4. 🗑️  Видалити статтю (за ID)
  5. 🗑️  Масове видалення
  6. 📅 Видалення за датою
  7. 📤 Експорт статей
  8. 🔄 Dry-run видалення
  0. ❌ Вихід
""")


def main():
    """Головна функція"""
    if not DATABASE_URL:
        print_error("DATABASE_URL не налаштовано!")
        sys.exit(1)
    
    while True:
        show_menu()
        
        choice = input(f"{Colors.CYAN}Ваш вибір: {Colors.END}").strip()
        
        try:
            if choice == '1':
                limit = input("Кількість статей (за замовчуванням 20): ").strip()
                limit = int(limit) if limit else 20
                status = input("Фільтр статусу (pending/approved/posted/rejected або Enter для всіх): ").strip()
                list_recent_articles(limit, status if status else None)
                
            elif choice == '2':
                keyword = input("Введіть ключове слово для пошуку: ").strip()
                if keyword:
                    search_articles(keyword)
                    
            elif choice == '3':
                article_id = input("Введіть ID статті: ").strip()
                if article_id.isdigit():
                    show_article_details(int(article_id))
                    
            elif choice == '4':
                article_id = input("Введіть ID статті для видалення: ").strip()
                if article_id.isdigit():
                    delete_article(int(article_id))
                    
            elif choice == '5':
                ids_input = input("Введіть ID статей через кому (наприклад: 1,2,3): ").strip()
                if ids_input:
                    ids = [int(x.strip()) for x in ids_input.split(',') if x.strip().isdigit()]
                    if ids:
                        bulk_delete(ids)
                        
            elif choice == '6':
                start = input("Дата початку (YYYY-MM-DD): ").strip()
                end = input("Дата кінця (YYYY-MM-DD): ").strip()
                status = input("Фільтр статусу (або Enter для всіх): ").strip()
                if start and end:
                    delete_by_date_range(start, end, status if status else None)
                    
            elif choice == '7':
                export_articles()
                
            elif choice == '8':
                article_id = input("Введіть ID для dry-run: ").strip()
                if article_id.isdigit():
                    delete_article(int(article_id), dry_run=True)
                    
            elif choice == '0':
                print_info("До побачення! 👋")
                break
                
            else:
                print_warning("Невірний вибір")
                
        except KeyboardInterrupt:
            print("\n")
            print_info("Перервано користувачем")
            break
        except Exception as e:
            print_error(f"Помилка: {e}")
        
        input(f"\n{Colors.CYAN}Натисніть Enter для продовження...{Colors.END}")


if __name__ == "__main__":
    main()

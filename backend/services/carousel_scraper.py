from playwright.async_api import async_playwright
import asyncio
import re

async def scrape_product_carousel(url: str, brand_name: str = None) -> dict:
    """
    Scrape product details by clicking through carousel items.
    First looks for Products nav link, then scrapes carousel items.
    """
    print(f"🔍 Starting click-through carousel scraper for {url}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=45000)
            print("✅ Page loaded, looking for Products nav link...")
            await page.wait_for_timeout(2000)
            
            nav_keywords = [
                'products', 'product', 'продукція', 'продукти', 'товари',
                'portfolio', 'brands', 'бренди', 'асортимент', 'каталог',
                'catalog', 'range', 'collection', 'колекція'
            ]
            
            nav_clicked = False
            nav_selectors = ['nav a', 'header a', '.menu a', '.nav a', 'a[href*="product"]', 'a[href*="catalog"]']
            
            for nav_sel in nav_selectors:
                if nav_clicked:
                    break
                links = await page.query_selector_all(nav_sel)
                for link in links:
                    try:
                        text = await link.inner_text()
                        href = await link.get_attribute('href') or ''
                        text_lower = text.lower().strip()
                        href_lower = href.lower()
                        
                        if any(kw in text_lower or kw in href_lower for kw in nav_keywords):
                            print(f"🔗 Found Products nav link: '{text}' -> {href}")
                            await link.click()
                            await page.wait_for_timeout(3000)
                            nav_clicked = True
                            print("✅ Navigated to Products page")
                            break
                    except:
                        continue
            
            if not nav_clicked:
                print("ℹ️ No Products nav link found, staying on current page")
            
            await page.wait_for_timeout(2000)
            
            product_containers = []
            container_selectors = [
                '.product', '.product-card', '.product-item', '.item',
                '.swiper-slide', '.slick-slide', '.carousel-item',
                '[class*="product"]', '[class*="item"]', '[class*="card"]',
                'a[href*="product"]', 'a[href*="#"]'
            ]
            
            found_selector = None
            for selector in container_selectors:
                containers = await page.query_selector_all(selector)
                if containers and len(containers) > 1:
                    print(f"✅ Found {len(containers)} containers with: {selector}")
                    product_containers = containers
                    found_selector = selector
                    break
            
            if not product_containers:
                print("⚠️ No product containers found, falling back to text extraction")
                raw_text = await page.evaluate('() => document.body.innerText')
                await browser.close()
                return {'products': [], 'raw_text': raw_text, 'carousel_detected': False}
            
            print(f"📦 Found {len(product_containers)} product containers to click through")
            
            products = []
            
            for idx in range(min(len(product_containers), 20)):
                try:
                    print(f"  🖱️  Clicking product {idx + 1}/{min(len(product_containers), 20)}...")
                    
                    containers = await page.query_selector_all(found_selector)
                    if idx >= len(containers):
                        break
                    
                    container = containers[idx]
                    
                    href = await container.get_attribute('href')
                    
                    await container.click()
                    await page.wait_for_timeout(2000)
                    
                    product_info = await page.evaluate('''() => {
                        const getText = (selectors) => {
                            if (typeof selectors === 'string') selectors = [selectors];
                            for (let selector of selectors) {
                                const elements = document.querySelectorAll(selector);
                                for (let el of elements) {
                                    if (el && el.innerText && el.innerText.trim()) {
                                        return el.innerText.trim();
                                    }
                                }
                            }
                            return '';
                        };
                        
                        const modal = document.querySelector('.modal, [role="dialog"], .popup, [class*="modal"], [class*="popup"]');
                        const context = modal || document.body;
                        
                        return {
                            name: getText([
                                'h1', 'h2', 'h3',
                                '.product-name', '.product-title', '.name', '.title',
                                '[class*="product-name"]', '[class*="title"]'
                            ]),
                            size: getText([
                                '.size', '.volume', '.capacity', '.ml', '.liters',
                                '[class*="size"]', '[class*="volume"]', '[class*="capacity"]'
                            ]),
                            abv: getText([
                                '.abv', '.alcohol', '.strength', '.percent',
                                '[class*="abv"]', '[class*="alcohol"]', '[class*="strength"]'
                            ]),
                            price: getText([
                                '.price', '[class*="price"]', '[data-price]'
                            ]),
                            description: getText([
                                '.description', '.desc', '.details', '.info',
                                '[class*="description"]', '[class*="details"]',
                                'p', '.text'
                            ]),
                            features: getText([
                                '.features', '.characteristics', '.specs',
                                '[class*="features"]', '[class*="characteristics"]'
                            ]),
                            allText: (modal || context).innerText || ''
                        };
                    }''')
                    
                    if (product_info.get('name') or 
                        product_info.get('size') or 
                        len(product_info.get('allText', '')) > 50):
                        
                        cleaned = {
                            'name': product_info.get('name', '').strip(),
                            'size': product_info.get('size', '').strip(),
                            'abv': product_info.get('abv', '').strip(),
                            'price': product_info.get('price', '').strip(),
                            'description': product_info.get('description', '').strip()[:300],
                            'features': product_info.get('features', '').strip()[:300],
                            'allText': product_info.get('allText', '').strip()[:500]
                        }
                        
                        products.append(cleaned)
                        print(f"    ✅ Extracted: {cleaned['name'][:50] or 'Product ' + str(idx+1)}")
                    
                    close_selectors = [
                        'button[class*="close"]', '[data-dismiss]', '.close',
                        '[aria-label*="close"]', '[aria-label*="Close"]'
                    ]
                    
                    closed = False
                    for close_sel in close_selectors:
                        close_btn = await page.query_selector(close_sel)
                        if close_btn:
                            try:
                                await close_btn.click()
                                await page.wait_for_timeout(500)
                                closed = True
                                break
                            except:
                                pass
                    
                    if not closed:
                        if href and href.startswith('#'):
                            await page.keyboard.press('Escape')
                            await page.wait_for_timeout(500)
                        else:
                            await page.go_back()
                            await page.wait_for_timeout(1500)
                
                except Exception as e:
                    print(f"    ⚠️ Error processing product {idx + 1}: {e}")
                    try:
                        await page.goto(url, wait_until="networkidle", timeout=15000)
                        await page.wait_for_timeout(2000)
                    except:
                        pass
                    continue
            
            await page.goto(url, wait_until="networkidle")
            raw_text = await page.evaluate('() => document.body.innerText')
            
            await browser.close()
            
            print(f"✅ Click-through complete: {len(products)} products extracted")
            
            return {
                'products': products,
                'raw_text': raw_text,
                'carousel_detected': True,
                'product_count': len(products)
            }
            
        except Exception as e:
            await browser.close()
            print(f"❌ Click-through scraping error: {e}")
            return {
                'products': [],
                'raw_text': '',
                'error': str(e),
                'carousel_detected': False
            }


def create_product_enrichment(products: list, brand_name: str, company_name: str, url: str) -> str:
    """Create rich text description from product details."""
    if not products:
        return ""
    
    lines = [f"\n{brand_name} Product Line and Range:\n"]
    lines.append(f"{brand_name} offers the following products:\n")
    
    for idx, product in enumerate(products, 1):
        name = product.get('name', f'{brand_name} Product {idx}')
        size = product.get('size', '')
        abv = product.get('abv', '')
        price = product.get('price', '')
        desc = product.get('description', '')
        features = product.get('features', '')
        all_text = product.get('allText', '')
        
        parts = [f"{idx}. {name}"]
        if size: parts.append(f"Volume: {size}")
        if abv: parts.append(f"Alcohol: {abv}")
        if price: parts.append(f"Price: {price}")
        if desc: parts.append(f"Description: {desc}")
        if features: parts.append(f"Features: {features}")
        elif all_text and len(all_text) > 20:
            parts.append(f"Details: {all_text[:150]}")
        
        lines.append(" | ".join(parts))
    
    enriched = f"""
{brand_name} is a {'brand distributed by ' + company_name if company_name != brand_name else 'premium brand'}.

Product Portfolio:
{chr(10).join(lines)}

Total products in {brand_name} range: {len(products)}

All {brand_name} products are available for distribution.
Official website: {url}
    """.strip()
    
    return enriched

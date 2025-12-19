from playwright.async_api import async_playwright
import asyncio
import re

async def scrape_product_carousel(url: str, brand_name: str = None) -> dict:
    """
    Scrape product details from JavaScript carousels.
    Returns: {products: [{name, size, abv, price, description}], raw_text, carousel_detected}
    """
    print(f"🔍 Starting carousel scraper for {url}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=45000)
            print("✅ Page loaded, waiting for dynamic content...")
            
            await page.wait_for_timeout(4000)
            
            carousel_selectors = [
                '.carousel', '.slider', '.swiper', '.slick-slider',
                '[class*="carousel"]', '[class*="slider"]', '[class*="swiper"]',
                '[data-carousel]', '[data-slider]', '[id*="carousel"]'
            ]
            
            carousel_found = False
            for selector in carousel_selectors:
                elements = await page.query_selector_all(selector)
                if elements:
                    carousel_found = True
                    print(f"✅ Found carousel with selector: {selector}")
                    break
            
            if carousel_found:
                print("🔄 Attempting to navigate carousel...")
                
                next_selectors = [
                    'button[class*="next"]', 'button[class*="arrow-right"]',
                    '.swiper-button-next', '.slick-next', '[data-role="next"]',
                    'a[class*="next"]', '.carousel-control-next'
                ]
                
                for selector in next_selectors:
                    buttons = await page.query_selector_all(selector)
                    if buttons:
                        print(f"✅ Found navigation buttons: {selector}")
                        for i in range(15):
                            try:
                                await buttons[0].click()
                                await page.wait_for_timeout(300)
                            except Exception as e:
                                print(f"⚠️ Click {i+1} failed: {e}")
                                break
                        break
            
            await page.wait_for_timeout(2000)
            
            products = []
            
            product_selectors = [
                '.product', '.product-card', '.product-item',
                '[class*="product"]', '[class*="item"]', '[class*="card"]',
                '.swiper-slide', '.slick-slide', '.carousel-item'
            ]
            
            all_cards = []
            for selector in product_selectors:
                cards = await page.query_selector_all(selector)
                if cards:
                    print(f"✅ Found {len(cards)} elements with selector: {selector}")
                    all_cards.extend(cards)
            
            unique_cards = list(set(all_cards))[:30]
            print(f"📦 Processing {len(unique_cards)} unique product cards...")
            
            for idx, card in enumerate(unique_cards):
                try:
                    product_info = await card.evaluate('''(element) => {
                        const getText = (selectors) => {
                            if (typeof selectors === 'string') selectors = [selectors];
                            for (let selector of selectors) {
                                const el = element.querySelector(selector);
                                if (el && el.innerText) return el.innerText.trim();
                            }
                            return '';
                        };
                        
                        const name = getText([
                            'h1', 'h2', 'h3', 'h4', 'h5',
                            '.name', '.title', '.product-name', '.product-title',
                            '[class*="name"]', '[class*="title"]'
                        ]);
                        
                        const size = getText([
                            '.size', '.volume', '.capacity',
                            '[class*="size"]', '[class*="volume"]', '[class*="capacity"]'
                        ]);
                        
                        const abv = getText([
                            '.abv', '.alcohol', '.strength',
                            '[class*="abv"]', '[class*="alcohol"]'
                        ]);
                        
                        const price = getText([
                            '.price', '[class*="price"]', '[data-price]'
                        ]);
                        
                        const description = getText([
                            '.description', '.desc', 'p',
                            '[class*="description"]', '[class*="desc"]'
                        ]);
                        
                        const allText = element.innerText || '';
                        
                        return {
                            name: name,
                            size: size,
                            abv: abv,
                            price: price,
                            description: description,
                            allText: allText.substring(0, 200)
                        };
                    }''')
                    
                    if (product_info.get('name') or 
                        product_info.get('size') or 
                        len(product_info.get('allText', '')) > 20):
                        
                        cleaned = {
                            'name': product_info.get('name', ''),
                            'size': product_info.get('size', ''),
                            'abv': product_info.get('abv', ''),
                            'price': product_info.get('price', ''),
                            'description': product_info.get('description', ''),
                            'allText': product_info.get('allText', '')
                        }
                        products.append(cleaned)
                        print(f"  ✅ Product {idx+1}: {cleaned['name'][:50] or 'Unnamed'}")
                
                except Exception as e:
                    print(f"  ⚠️ Failed to extract from card {idx+1}: {e}")
                    continue
            
            raw_text = await page.evaluate('''() => {
                const scripts = document.querySelectorAll('script, style, noscript');
                scripts.forEach(s => s.remove());
                return document.body.innerText || document.body.textContent;
            }''')
            
            await browser.close()
            
            print(f"✅ Carousel scraping complete: {len(products)} products, {len(raw_text)} chars text")
            
            return {
                'products': products,
                'raw_text': raw_text,
                'carousel_detected': carousel_found,
                'product_count': len(products)
            }
            
        except Exception as e:
            await browser.close()
            print(f"❌ Carousel scraping error: {e}")
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
        all_text = product.get('allText', '')
        
        parts = [f"{idx}. {name}"]
        if size: parts.append(f"Volume: {size}")
        if abv: parts.append(f"Alcohol: {abv}")
        if price: parts.append(f"Price: {price}")
        if desc: parts.append(f"Description: {desc}")
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

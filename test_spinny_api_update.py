"""
Quick test to verify the updated Spinny API endpoint works.
"""

import asyncio
import logging
from scraper import scrape_spinny

# Enable logging to see what's happening
logging.basicConfig(level=logging.INFO)

async def test_spinny():
    print("Testing updated Spinny scraper with new API endpoint...")
    print("=" * 80)
    
    results = await scrape_spinny(max_pages=1)
    
    print(f"\nResults: {len(results)} listings")
    print("=" * 80)
    
    if results:
        print("\nFirst 3 listings:")
        for i, listing in enumerate(results[:3], 1):
            print(f"\n{i}. {listing['title']}")
            print(f"   Price: ₹{listing['price']} Lakh")
            print(f"   KM: {listing['km']}")
            print(f"   Year: {listing['year']}")
            print(f"   Fuel: {listing['fuel_type']}")
            print(f"   Link: {listing['link']}")
    else:
        print("\n❌ No results returned - API may still be broken")
    
    return results

if __name__ == "__main__":
    results = asyncio.run(test_spinny())
    
    # Verify results meet bug condition criteria
    if len(results) > 0:
        print("\n" + "=" * 80)
        print("✅ SUCCESS: Spinny API returned results!")
        print("=" * 80)
        
        # Check if prices are in valid range
        valid_prices = [r for r in results if 1.0 <= r['price'] <= 200.0]
        print(f"\nValid prices (1-200 Lakh): {len(valid_prices)}/{len(results)}")
        
        # Check if km values are valid
        valid_km = [r for r in results if r['km'] is None or (0 <= r['km'] <= 500000)]
        print(f"Valid km (0-500k or None): {len(valid_km)}/{len(results)}")
        
        # Check if years are valid
        valid_years = [r for r in results if r['year'] is None or (2000 <= r['year'] <= 2026)]
        print(f"Valid years (2000-2026 or None): {len(valid_years)}/{len(results)}")
    else:
        print("\n" + "=" * 80)
        print("❌ FAILED: Spinny API returned 0 results")
        print("=" * 80)

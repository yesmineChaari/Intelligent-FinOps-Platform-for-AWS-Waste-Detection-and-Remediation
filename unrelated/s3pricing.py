import asyncio
import os
import requests
import asyncpg
from dotenv import load_dotenv

load_dotenv()


AWS_S3_PRICING_URL = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonS3/current/index.json"

def fetch_and_parse_s3_pricing() -> list[tuple]:
    """
    Downloads the AWS S3 Pricing JSON and extracts relevant GB/Month storage costs.
    Returns a list of tuples formatted for asyncpg executemany().
    """
    print(f"Downloading S3 Pricing Data from {AWS_S3_PRICING_URL}...")
    print("Note: This file is large (~150MB+), this may take a minute or two.")
    
    response = requests.get(AWS_S3_PRICING_URL)
    response.raise_for_status()
    data = response.json()
    
    products = data.get('products', {})
    terms = data.get('terms', {}).get('OnDemand', {})
    
    storage_class_map = {
        "General Purpose": "Standard",
        "Infrequent Access": "Standard-IA",
        "Archive": "Glacier",
        "Deep Archive": "Deep Archive"
    }

    extracted_records = []

    for sku, product in products.items():
        attr = product.get('attributes', {})
        product_family = product.get('productFamily') or attr.get('productFamily')
        service_code = attr.get('servicecode') or attr.get('serviceCode')
        if product_family == 'Storage' and service_code == 'AmazonS3':
            region = attr.get('regionCode')
            raw_storage_class = attr.get('storageClass')
            usage_type = attr.get('usagetype')
            
            if not region or not raw_storage_class:
                continue
            
            clean_storage_class = storage_class_map.get(raw_storage_class)
            if not clean_storage_class:
                continue

            sku_terms = terms.get(sku, {})
            for offer_term_code, offer_details in sku_terms.items():
                price_dimensions = offer_details.get('priceDimensions', {})
                
                for rate_code, rate_details in price_dimensions.items():
                    unit = rate_details.get('unit', '').lower()
                    if 'gb-mo' in unit or 'gb-month' in unit:
                        price_str = rate_details.get('pricePerUnit', {}).get('USD')
                        
                        if price_str is not None:
                            price_float = float(price_str)
                            extracted_records.append((
                                region, 
                                clean_storage_class, 
                                usage_type, 
                                price_float, 
                                'USD'
                            ))
                            
    return extracted_records

async def update_database(prices: list[tuple]):
    """
    Connects to the Neon Postgres database and upserts the pricing data.
    """
    db_url = os.getenv("NEON_DATABASE_URL")
    if not db_url:
        raise ValueError("NEON_DATABASE_URL environment variable is missing!")

    print(f"Connecting to database to upsert {len(prices)} price records...")
    conn = await asyncpg.connect(db_url)
    
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS s3_pricing (
                region VARCHAR(50),
                storage_class VARCHAR(50),
                usage_type VARCHAR(100),
                price_per_gb_month NUMERIC(12, 6),
                currency VARCHAR(10) DEFAULT 'USD',
                updated_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (region, storage_class, usage_type)
            );
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_s3_pricing_lookup 
            ON s3_pricing (region, storage_class);
        """)

        query = """
            INSERT INTO s3_pricing (region, storage_class, usage_type, price_per_gb_month, currency, updated_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (region, storage_class, usage_type) 
            DO UPDATE SET 
                price_per_gb_month = EXCLUDED.price_per_gb_month,
                currency = EXCLUDED.currency,
                updated_at = NOW();
        """
        
        await conn.executemany(query, prices)
        print("Database update complete! S3 pricing is up to date.")

    finally:
        await conn.close()


async def main():
    try:
        print("--- Starting S3 Pricing Update Job ---")
        prices = fetch_and_parse_s3_pricing()
        
        if not prices:
            print("Warning: No pricing data extracted. AWS JSON might have changed format.")
            return
            
        await update_database(prices)
        print("--- Job Finished Successfully ---")
        
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
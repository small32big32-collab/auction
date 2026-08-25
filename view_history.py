from supabase import create_client

SUPABASE_URL = "https://mdursbqpogprwzbhjzxz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1kdXJzYnFwb2dwcnd6Ymhqenh6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NzE0MzU5NCwiZXhwIjoyMTAyNzE5NTk0fQ.AXb2IUi3VOY1hNHxrvZUpsk4f6ycGDc2qaC_4zzM1Mo"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def print_price_history(item_id: str):
    res = (
        supabase.table("price_history")
        .select("*")
        .eq("item_id", item_id)
        .order("created_at", desc=True)
        .execute()
    )
    
    records = res.data
    if not records:
        print("История цен для этого предмета пока пуста.")
        return

    print("=" * 60)
    print(f" История цен: {records[0]['item_name']} (ID: {item_id})")
    print("=" * 60)
    print(f"{'Дата и время':<22} | {'Мин. выкуп':<12} | {'Всего лотов':<10}")
    print("-" * 60)
    
    for r in records:
        date_str = r['created_at'][:19].replace("T", " ")
        price = f"{r['min_buyout_price']:,}".replace(",", " ")
        print(f"{date_str:<22} | {price:<12} | {r['total_lots']:<10}")
    print("-" * 60)

if __name__ == "__main__":
    print_price_history("04yr")
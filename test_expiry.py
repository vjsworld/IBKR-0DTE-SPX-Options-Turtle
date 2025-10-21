from datetime import datetime, timedelta

def calculate_expiry_date(offset: int) -> str:
    """Test version of calculate_expiry_date"""
    current_date = datetime(2025, 10, 21)  # Tuesday, Oct 21, 2025
    target_date = current_date
    
    # SPX has daily expirations Monday-Friday
    expiry_days = [0, 1, 2, 3, 4]
    
    days_checked = 0
    expirations_found = 0
    
    print(f"\nTesting offset={offset}")
    print(f"Start date: {current_date.strftime('%Y-%m-%d %A')} (weekday {current_date.weekday()})")
    print()
    
    # Find the Nth expiration (where N = offset)
    while True:
        is_expiry = target_date.weekday() in expiry_days
        print(f"Day {days_checked}: {target_date.strftime('%Y-%m-%d %A')} (weekday {target_date.weekday()}) - Is expiry: {is_expiry}")
        
        if is_expiry:
            print(f"  -> Expiration #{expirations_found} found")
            if expirations_found == offset:
                result = target_date.strftime("%Y%m%d")
                print(f"  -> MATCH! Returning {result}")
                return result
            expirations_found += 1
        
        target_date += timedelta(days=1)
        days_checked += 1
        
        if days_checked > 10:
            break
    
    return "ERROR"

# Test offsets 0-5
for i in range(6):
    result = calculate_expiry_date(i)
    date_obj = datetime.strptime(result, "%Y%m%d")
    print(f"\n✓ Offset {i}: {result} = {date_obj.strftime('%A, %B %d, %Y')}")
    print("=" * 60)

from datetime import datetime, timedelta


def am_i_working_now(cycle_start: datetime) -> bool:
    now = datetime.now()

    days_in_cycle = (now - cycle_start).days % 8

    # 0, 1, 2, 3 - work days
    if days_in_cycle < 4:
        # day shift
        if days_in_cycle < 2:
            # weekend
            if now.weekday() == 5 or now.weekday() == 6:
                start_time = now.replace(hour=9, minute=45)
                end_time = now.replace(hour=22, minute=0)
            else:
                start_time = now.replace(hour=13, minute=30)
                end_time = now.replace(hour=22, minute=0)

            if start_time <= now < end_time:
                return True
            else:
                return False

        else:
            # night shift
            start_time = now.replace(hour=21, minute=45)
            end_time = (now + timedelta(days=1)).replace(hour=10, minute=0)

            if (now >= start_time) or (now < end_time and now.hour < 10):
                return True
            else:
                return False

    else:
        return False

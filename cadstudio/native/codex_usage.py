"""Read-only subscription usage. Percentages are not a remaining-token balance."""
from datetime import datetime
import math


def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def normalize_usage(payload):
    if not isinstance(payload,dict):return {'buckets':[]}
    by_id=payload.get('rateLimitsByLimitId')
    if isinstance(by_id,dict):
        entries=by_id.items()
    else:
        legacy=payload.get('rateLimits')
        entries=[(legacy.get('limitId') or 'codex',legacy)] if isinstance(legacy,dict) else []
    buckets=[]
    for identifier,raw in entries:
        if not isinstance(raw,dict):continue
        windows=[]
        for key in ('primary','secondary'):
            window=raw.get(key)
            if not isinstance(window,dict):continue
            used=window.get('usedPercent');duration=window.get('windowDurationMins');reset=window.get('resetsAt')
            windows.append(dict(remaining=max(0,min(100,100-used)) if number(used) else None,
                minutes=duration if number(duration) and duration>0 else None,
                resets_at=reset if number(reset) and reset>0 else None))
        # Retain only display fields; never store auth/account IDs or reset credits.
        buckets.append(dict(id=str(identifier)[:100],windows=windows))
    return {'buckets':buckets,'checked_at':datetime.now().astimezone().isoformat(timespec='seconds')}


def usage_text(usage):
    buckets=(usage or {}).get('buckets',[])
    main=next((item for item in buckets if item['id']=='codex'),None)
    windows=main['windows'] if main else []
    rows=[]
    weekly=next((window for window in windows if window['minutes']==10080),None)
    def describe(window,name):
        remaining=window['remaining'];text=name+' · '+(f"{remaining:g}% 남음" if remaining is not None else '잔여량 확인 불가')
        if window.get('resets_at'):
            try:text+=' · 초기화 '+datetime.fromtimestamp(window['resets_at']).astimezone().strftime('%m/%d %H:%M %Z')
            except (OSError,OverflowError,ValueError):pass
        return text
    rows.append(describe(weekly,'Codex 주간') if weekly else 'Codex 주간 · 잔여량 확인 불가')
    for window in windows:
        if window is weekly:continue
        minutes=window['minutes']
        name=f'Codex {minutes/60:g}시간' if minutes is not None and minutes%60==0 else f'Codex {minutes:g}분' if minutes else 'Codex 기타 한도'
        rows.append(describe(window,name))
    if (usage or {}).get('checked_at'):
        try:rows.append('조회 '+datetime.fromisoformat(usage['checked_at']).strftime('%m/%d %H:%M'))
        except (TypeError,ValueError):pass
    return '\n'.join(rows)


USAGE_NOTE='계정 전체에서 공유하는 Codex 사용량입니다. 실제 남은 토큰 개수는 제공되지 않습니다. 새로고침으로 확인하며 자동 구매나 한도 초기화는 하지 않습니다.'

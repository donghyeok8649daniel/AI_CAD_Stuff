"""Show measured geometry before the model's unverified description."""


def draft_summary(response, preview):
    stats=preview['stats']
    def size(values):return ' × '.join(f'{v:,.2f}' for v in values)+' mm'
    lines=['CAD 계산 결과',f"전체 크기 (X × Y × Z): {size(stats['bounds'])}",
           f"{stats['parts']}개 부품 · 체적 {stats['volume']:,.2f} mm³"]
    for mesh in preview.get('meshes',[]):
        lines.append(f"• {mesh['name']}: {size(mesh['bounds'])} · 색상 {mesh['color']}")
    lines+=['','AI 설명 · 추정과 설명은 실제 형상과 다를 수 있습니다.',response['summary']]
    lines+=response.get('changes',[])+response.get('assumptions',[])
    return '\n'.join(lines)

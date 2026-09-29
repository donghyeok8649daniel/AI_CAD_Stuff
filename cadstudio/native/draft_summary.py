"""Show measured geometry before the model's unverified description."""


def draft_summary(response, preview):
    stats=preview['stats']
    def size(values):return ' × '.join(f'{v:,.2f}' for v in values)+' mm'
    review=response.get('validation',{})
    lines=(['미리보기 준비 · 간섭 수정 필요','현재 설계는 변경되지 않았습니다. 미리보기에서 간섭 부품을 확인하고 AI로 수정을 계속하세요.',*review.get('issues',[]),''] if review.get('status')=='needs_repair' else [])
    lines+=['CAD 계산 결과',f"전체 크기 (X × Y × Z): {size(stats['bounds'])}",
           f"{stats['parts']}개 부품 · 체적 {stats['volume']:,.2f} mm³"]
    for mesh in preview.get('meshes',[]):
        lines.append(f"• {mesh['name']}: {size(mesh['bounds'])} · 색상 {mesh['color']}")
    lines+=['','AI 설명 · 추정과 설명은 실제 형상과 다를 수 있습니다.',response['summary']]
    lines+=response.get('changes',[])+response.get('assumptions',[])
    return '\n'.join(lines)

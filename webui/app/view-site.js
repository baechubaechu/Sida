// The site page: facts, ordinance, planned uses and the find tab (HTML strings).

import { escapeHtml as escape, expertStatus, projectPath as projectUrl, expertPath, dateTime, sitePath, siteHeadline, areaText, zoneScope, missingText, SITE_PART_LABELS, UNKNOWN, restrictionGroups, buildingLine, chosenDong, ordinanceFigure, ordinanceApplies, ordinanceSends, useResult, useError, useDefinitions } from './model.js';
import { REGION_LABELS, REGION_LEVELS, currentRoute, expertById, jobRunning, ui } from './state.js';

// ------------------------------------------------------------------ site page

const listOr = (items, empty) => (items.length ? `<ul>${items.join('')}</ul>` : `<p class="muted">${escape(empty)}</p>`);

function siteSection(title, inner, extra = '') {
  return `<section class="doc-section ${extra}"><h2>${escape(title)}</h2>${inner}</section>`;
}

function zoningBlock(name, site) {
  const s = site.summary;
  if (!s.zoning.length) return siteSection('용도지역', `<p>용도지역: ${UNKNOWN}</p>`);
  const rows = s.zoning.map((z) => `<tr><th scope="row">${escape(z.zone)}</th><td>${escape(zoneScope(z, s.parcel_count))}</td>
      <td>${escape(z.bcr_max)}% 이하</td><td>${escape(z.far_min)}~${escape(z.far_max)}%</td></tr>`).join('');
  return siteSection('용도지역', `<div class="table-wrap"><table class="site-table">
      <thead><tr><th scope="col">용도지역</th><th scope="col">범위</th><th scope="col">건폐율 법정 상한</th><th scope="col">용적률 법정 범위</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <p class="muted small-text">법정 범위입니다. 실제 적용값은 ${escape(s.municipality || '해당 지자체')} 도시계획 조례가 이 범위 안에서 정합니다. <a href="${sitePath(name, 'ordinance')}">조례 보기</a></p>`, 'site-zoning');
}

function parcelItem(p) {
  const traits = [`면적 ${areaText(p.area_m2)}`, p.land_category && `지목 ${p.land_category}`, p.use && `이용 상황 ${p.use}`, p.road_side && `도로 접면 ${p.road_side}`]
    .filter(Boolean).join(' · ');
  const missing = p.errors.map((what) => SITE_PART_LABELS[what] || what);
  return `<li><strong>${escape(p.address || p.pnu)}</strong>${p.road_address ? `<span class="muted"> · ${escape(p.road_address)}</span>` : ''}
    <br>${escape(traits)}${missing.length ? `<br><span class="unknown">${UNKNOWN}: ${escape(missing.join(', '))}</span>` : ''}</li>`;
}

function buildingsBlock(site) {
  const many = site.parcels.length > 1;
  const items = site.parcels.flatMap((p) => {
    const where = many ? `<span class="muted">${escape(p.address || p.pnu)}</span> ` : '';
    if (p.buildings === null || p.buildings === undefined) return [`<li>${where}<span class="unknown">건축물대장 ${UNKNOWN}</span></li>`];
    if (!p.buildings.length) return [`<li>${where}등록된 건물 없음</li>`];
    return p.buildings.map((b) => `<li>${where}${escape(buildingLine(b))}</li>`);
  });
  return siteSection('기존 건축물 (건축물대장)', listOr(items, '필지가 없습니다.'));
}

function restrictionsBlock(site) {
  if (!site.restrictions.length) {
    return siteSection('건축제한 근거 조문', '<p class="muted">이 대지를 조회할 때는 가져오지 않았습니다. 다시 조회하면 채워집니다.</p>');
  }
  const many = site.restrictions.length > 1;
  const law = (l) => `<li>${escape(l.text)}${l.zones?.length ? ` <span class="muted small-text">${escape(l.zones.join(', '))}</span>` : ''}</li>`;
  const inner = site.restrictions.map((r) => {
    const { national, local, error } = restrictionGroups(r);
    const head = many ? `<h3>시·군·구 ${escape(r.area)}</h3>` : '';
    if (error) return `${head}<p class="unknown">가져오지 못했습니다(${escape(error)}). ${UNKNOWN}</p>`;
    if (!national.length && !local.length) return `${head}<p class="muted">해당하는 조문이 없습니다.</p>`;
    return `${head}<div class="doc-row cols-2">
        <div><h3>국가 법령</h3>${national.length ? `<ul>${national.map(law).join('')}</ul>` : '<p class="muted">없음</p>'}</div>
        <div><h3>조례</h3>${local.length ? `<ul>${local.map(law).join('')}</ul>` : '<p class="muted">없음</p>'}</div></div>`;
  }).join('');
  return siteSection('건축제한 근거 조문', `${inner}<p class="muted small-text">정부 응답에 법령 이름이 없어 조문 제목만 보여 줍니다.</p>`);
}

// Before any site is saved (or while loading): what the facts, ordinance and uses tabs show instead.
function siteNotYet(name) {
  const site = ui.site;
  if (!site) return `<p class="${ui.siteError ? 'error-text' : 'muted'}">${escape(ui.siteError || '불러오는 중입니다.')}</p>`;
  if (site.available) return '';
  return `<div class="expert-note"><p>아직 대지를 조회하지 않았습니다. 주소로 필지를 찾아 저장하면 정부 데이터에서 용도지역, 법정 건폐율·용적률, 조례, 기존 건축물, 건축제한 근거 조문을 가져옵니다.</p>
      <p class="note-actions"><a class="primary small" href="${sitePath(name, 'find')}">대지 찾기</a></p></div>`;
}

function factsTab(name) {
  const site = ui.site;
  const notYet = siteNotYet(name);
  if (notYet) return notYet;
  const s = site.summary;
  const overview = [
    `<li>필지 ${s.parcel_count}개${s.parcel_count > 1 ? '를 하나의 대지로 봄' : ''}</li>`,
    `<li>합계 면적 ${escape(areaText(s.total_area_m2))}${s.area_complete ? '' : ` <span class="unknown">(일부 필지 면적 ${UNKNOWN})</span>`}</li>`,
    `<li>조례를 정하는 지자체 ${escape(s.municipality || UNKNOWN)}</li>`,
  ].join('');
  const districts = s.districts.map((d) => `<li>${escape(d.name)} <span class="muted">${escape(d.relation)}</span></li>`);
  const roads = s.roads.map((r) => `<li>${escape(r.name)} <span class="muted">${escape(r.relation)}</span></li>`);
  const flags = s.flags.length ? siteSection('확인 필요', `<ul>${s.flags.map((f) => `<li>${escape(f)}</li>`).join('')}</ul>`, 'site-flags') : '';
  const missing = s.missing.length
    ? siteSection(UNKNOWN, `<ul>${s.missing.map((m) => `<li>${escape(missingText(m))}</li>`).join('')}</ul><p class="muted small-text">가져오지 못한 항목은 추정하지 않습니다. 다시 조회해 보세요.</p>`)
    : '';
  return `<div class="doc-row top">${siteSection('대지', `<ul>${overview}</ul>`)}</div>
    <div class="doc-row">${zoningBlock(name, site)}</div>
    ${flags ? `<div class="doc-row">${flags}</div>` : ''}
    <div class="doc-row cols-2">${siteSection('그 밖의 지역·지구', listOr(districts, '없음'))}${siteSection('도시계획 도로', listOr(roads, '없음'))}</div>
    <div class="doc-row">${siteSection('필지', `<ul class="card-list">${site.parcels.map(parcelItem).join('')}</ul>`)}</div>
    <div class="doc-row">${buildingsBlock(site)}</div>
    <div class="doc-row">${restrictionsBlock(site)}</div>
    ${missing ? `<div class="doc-row">${missing}</div>` : ''}
    <details class="raw-doc site-lines" ${ui.showSiteLines ? 'open' : ''}><summary>전문가가 받는 대지 사실 원문</summary><pre>${escape(site.lines.join('\n'))}</pre></details>`;
}

function regionSelect(level) {
  const f = ui.find;
  const list = f.lists[level];
  if (!list && f.loading !== level) return '';
  const chosen = f.chosen[level]?.code || '';
  const options = list
    ? `<option value="">고르세요</option>${list.map((r) => `<option value="${escape(r.code)}" ${r.code === chosen ? 'selected' : ''}>${escape(r.name)}</option>`).join('')}`
    : '<option value="">불러오는 중…</option>';
  return `<label for="region-${level}">${REGION_LABELS[level]}</label>
    <select id="region-${level}" data-region="${level}" data-focus="region-${level}" ${list && !f.busy ? '' : 'disabled'}>${options}</select>`;
}

function candidateList() {
  const f = ui.find;
  if (!f.candidates) return '';
  if (!f.candidates.length) return '';
  const picked = new Set(f.picked.map((p) => p.pnu));
  return `<section class="candidates" aria-labelledby="candidates-title"><h2 id="candidates-title">찾은 필지 ${f.candidates.length}개</h2>
    <p class="muted small-text">대지로 쓸 필지를 고르세요. 여러 개를 고르면 하나의 대지로 합칩니다.</p>
    <ul>${f.candidates.map((c) => `<li><label><input type="checkbox" data-pick="${escape(c.pnu)}" ${picked.has(c.pnu) ? 'checked' : ''} ${f.busy ? 'disabled' : ''}>
      <span><strong>${escape(c.address || c.pnu)}</strong>${c.road_address ? `<span class="muted"> · ${escape(c.road_address)}</span>` : ''}${c.building ? `<span class="muted"> · ${escape(c.building)}</span>` : ''}</span></label></li>`).join('')}</ul></section>`;
}

function pickedBlock() {
  const f = ui.find;
  if (!f.picked.length) return '';
  const saving = f.busy === 'save';
  return `<section class="picked-lots" aria-labelledby="picked-title"><h2 id="picked-title">고른 필지 ${f.picked.length}개</h2>
    <ul class="picked-list">${f.picked.map((p) => `<li><span>${escape(p.address || p.pnu)}</span>
      <button type="button" class="icon-button" data-action="site-unpick" data-pnu="${escape(p.pnu)}" aria-label="${escape(p.address || p.pnu)} 빼기" ${f.busy ? 'disabled' : ''}>×</button></li>`).join('')}</ul>
    ${ui.site?.available ? '<p class="muted small-text">저장하면 지금 대지 사실을 새로 조회한 값으로 바꿉니다.</p>' : ''}
    ${saving ? '<p class="working" role="status"><span class="spinner" aria-hidden="true"></span>정부 데이터에서 대지 사실을 가져오는 중입니다. 몇 초 걸립니다.</p>' : ''}
    <div class="form-actions"><button type="button" class="primary" data-action="site-save" ${f.busy ? 'disabled' : ''}>이 필지로 대지 조회해 저장</button></div></section>`;
}

function mapBlock() {
  const f = ui.find;
  if (ui.mapError) {
    return `<p class="site-note warn">지도를 띄우지 못했습니다. ${escape(ui.mapError)} 지번이나 주소로는 찾을 수 있습니다.${ui.mapErrorStatus === 503 ? ' <button type="button" class="secondary small" data-action="settings">설정 열기</button>' : ''}</p>`;
  }
  const hint = f.mapBusy ? '누른 곳의 필지를 찾는 중입니다.' : '지도에서 필지를 누르면 고르고, 고른 필지를 다시 누르면 뺍니다. 지적선은 가까이 확대해야 보입니다.';
  return `<section class="site-map-wrap" aria-label="지도에서 필지 고르기">
    <div id="site-map-slot" class="site-map-slot">${ui.mapLayers ? '' : '<p class="muted">지도를 불러오는 중입니다.</p>'}</div>
    <p class="muted small-text" ${f.mapBusy ? 'role="status"' : ''}>${hint}</p></section>`;
}

function findTab() {
  const f = ui.find;
  const steps = f.mode === 'steps';
  const busy = Boolean(f.busy);
  const form = steps
    ? `<form class="site-form" id="lot-form" novalidate>
        <div class="region-grid">${REGION_LEVELS.map(regionSelect).join('')}</div>
        <fieldset class="lot-inputs"><legend>지번</legend>
          <label class="check"><input type="checkbox" data-lot="mountain" ${f.mountain ? 'checked' : ''}> 산</label>
          <label class="sr-only" for="lot-main">본번</label>
          <input id="lot-main" data-lot="main" data-focus="lot-main" inputmode="numeric" maxlength="4" placeholder="본번" value="${escape(f.main)}" autocomplete="off">
          <span aria-hidden="true">-</span>
          <label class="sr-only" for="lot-sub">부번 (선택)</label>
          <input id="lot-sub" data-lot="sub" data-focus="lot-sub" inputmode="numeric" maxlength="4" placeholder="부번 (선택)" value="${escape(f.sub)}" autocomplete="off">
          <button class="primary small" type="submit" ${busy || !chosenDong(f.chosen) ? 'disabled' : ''}>필지 찾기</button>
        </fieldset>
        <p class="muted small-text">부번을 비우면 그 본번의 필지가 모두 나옵니다.</p></form>`
    : `<form class="site-form" id="address-form" novalidate>
        <label for="site-query">지번 또는 도로명 주소</label>
        <div class="address-row"><input id="site-query" data-focus="site-query" maxlength="300" placeholder="예: 경기도 군포시 금정동 689" value="${escape(f.query)}" autocomplete="off">
          <button class="primary small" type="submit" ${busy ? 'disabled' : ''}>찾기</button></div>
        <p class="muted small-text">번지까지 적어 주세요. 오타는 고쳐 주지 않고, 건물·장소 이름으로는 찾지 않습니다.</p></form>`;
  const searching = f.busy === 'lots' || f.busy === 'search'
    ? '<p class="working" role="status"><span class="spinner" aria-hidden="true"></span>필지를 찾는 중입니다.</p>' : '';
  const error = f.error
    ? `<p class="error-text" role="alert">${escape(f.error)}${f.errorStatus === 503 ? ' <button type="button" class="secondary small" data-action="settings">설정 열기</button>' : ''}</p>` : '';
  return `<div class="site-find">
    <div class="mode-switch" role="group" aria-label="찾는 방법">
      <button type="button" data-action="site-mode" data-mode="steps" aria-pressed="${steps}">지역 고르기</button>
      <button type="button" data-action="site-mode" data-mode="text" aria-pressed="${!steps}">주소 붙여넣기</button></div>
    ${form}${searching}${error}${mapBlock()}${candidateList()}${pickedBlock()}</div>`;
}

function siteTab(name, tab) {
  if (tab === 'find') return findTab();
  if (tab === 'ordinance') return ordinanceTab(name);
  if (tab === 'uses') return usesTab(name);
  return factsTab(name);
}

// ---- 조례: every article on 건폐율·용적률, never filtered; figures only as read by rule, with their line.

function figureCell(figure) {
  const f = ordinanceFigure(figure);
  return `<td><strong class="${f.text === UNKNOWN ? 'unknown' : ''}">${escape(f.text)}</strong>
    ${f.note ? `<br><span class="unknown small-text">${escape(f.note)}</span>` : ''}
    ${f.quote ? `<blockquote class="law-quote">${escape(f.quote)}${f.label ? ` <span class="muted">${escape(f.label)}</span>` : ''}</blockquote>` : ''}</td>`;
}

function ordinanceItem(group, item) {
  const applies = ordinanceApplies(item);
  const busy = ui.ordinanceBusy === item.id;
  const detailed = group.id === 'site' ? '' : `<label class="check"><input type="checkbox" data-ord-detailed="${escape(item.id)}" ${item.detailed ? 'checked' : ''} ${item.dismissed || busy ? 'disabled' : ''}> 전문가가 원문 읽기</label>`;
  return `<li class="ord-item ${item.dismissed ? 'dismissed' : ''}">
    <div class="ord-head"><strong>${escape(item.label)} ${escape(item.title)}</strong>
      ${applies ? `<span class="status-badge ${applies.tone}">${escape(applies.text)}</span>` : ''}</div>
    <details class="law-text"><summary>원문</summary><pre>${escape(item.text)}</pre></details>
    <div class="ord-actions"><span class="muted small-text">${escape(ordinanceSends(group.id, item))}</span>
      ${detailed}
      <button type="button" class="secondary small" data-action="ord-dismiss" data-id="${escape(item.id)}" data-on="${!item.dismissed}" ${busy ? 'disabled' : ''}>${item.dismissed ? '다시 보이기' : '숨기기'}</button></div></li>`;
}

function ordinanceTab(name) {
  const notYet = siteNotYet(name);
  if (notYet) return notYet;
  const o = ui.ordinance;
  if (!o) return `<p class="${ui.ordinanceError ? 'error-text' : 'muted'}">${escape(ui.ordinanceError || '조례를 불러오는 중입니다.')}</p>`;
  if (!o.available) {
    return `<div class="expert-note"><p>${o.error ? `조례를 가져오지 못했습니다: ${escape(o.error)}.` : '이 대지의 도시계획 조례를 아직 가져오지 않았습니다.'} 건폐율·용적률은 ${UNKNOWN}입니다(대지 사실 탭의 법정 범위만 확인됨).</p>
      <p class="note-actions"><a class="secondary small" href="${sitePath(name, 'find')}">대지 다시 조회</a></p></div>`;
  }
  const rows = o.base.map((b) => `<tr><th scope="row">${escape(b.zone)}</th>${figureCell(b.bcr)}${figureCell(b.far)}</tr>`).join('');
  const base = siteSection('기본 수치', `<div class="table-wrap"><table class="site-table ord-table">
      <thead><tr><th scope="col">용도지역</th><th scope="col">건폐율</th><th scope="col">용적률</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="3" class="unknown">대지의 용도지역 줄을 찾지 못했습니다. ${UNKNOWN}</td></tr>`}</tbody></table></div>
    <p class="muted small-text">조문 줄에서 정해진 규칙으로 읽은 값입니다. 아래 지구·구역 조문이 대지에 해당하면 그 조문이 우선합니다.</p>`);
  const articles = siteSection('기본 수치를 정하는 조문', o.articles.map((a) => `<details class="law-text"><summary>${escape(a.label)} ${escape(a.title)}</summary><pre>${escape(a.text)}</pre>
      ${a.annex ? `<h3>${escape(a.annex.label || '별표')}</h3>${a.annex.text ? `<pre>${escape(a.annex.text)}</pre>` : `<p class="unknown">별표 파일을 읽지 못했습니다. 조례 원문에서 직접 확인해 주세요.</p>`}` : ''}</details>`).join(''));
  const groups = o.groups.map((g) => `<div class="doc-row">${siteSection(`${g.title} (${g.items.length})`, `<p class="muted small-text">${escape(g.note)}</p>
      ${g.items.length ? `<ul class="ord-list">${g.items.map((item) => ordinanceItem(g, item)).join('')}</ul>` : '<p class="muted">없음</p>'}`)}</div>`).join('');
  return `<p class="ord-name"><b>${escape(o.name)}</b>${o.effective ? ` <span class="muted">· 시행 ${escape(o.effective)}</span>` : ''}</p>
    <div class="doc-row">${base}</div>
    <div class="doc-row">${articles}</div>
    ${groups}
    <p class="muted small-text">숨기기와 원문 읽기는 이 프로젝트에 저장되고, 대지 분석가·법규 검토자가 받는 조례 글에 반영됩니다.</p>`;
}

// ---- 계획 용도: whether a use 토지이음 knows may be built in each of the site's zones.

function useCard(use) {
  const busy = ui.useFind.busy === `remove:${use.name}`;
  const head = `<div class="use-head"><h2>${escape(use.name)}</h2>
    <span class="muted small-text">조회 ${escape(dateTime(use.checked_at))}</span>
    <button type="button" class="icon-button" data-action="use-remove" data-use="${escape(use.name)}" aria-label="${escape(use.name)} 지우기" ${busy ? 'disabled' : ''}>×</button></div>`;
  if (use.error) return `<section class="doc-section use-card">${head}<p class="unknown">${escape(useError(use.error))}</p></section>`;
  if (!use.zones.length) return `<section class="doc-section use-card">${head}<p class="muted">이 대지의 용도지역·지구에는 이 용도에 대한 정보가 없습니다.</p></section>`;
  const zones = use.zones.map((z) => `<h3>${escape(z.zone || z.code)}${z.zone_law ? ` <span class="muted">${escape(z.zone_law)}</span>` : ''}</h3>
    <ul class="use-acts">${z.acts.map((a) => {
      const r = useResult(a.result);
      return `<li><span class="status-badge ${r.tone}">${escape(r.text)}</span> ${escape(a.act || '행위 미확인')}
        ${a.conditions.length ? `<div class="use-conditions"><span class="small-text muted">단서 조항</span>${a.conditions.map((c) => `<pre>${escape(c)}</pre>`).join('')}</div>` : ''}</li>`;
    }).join('')}</ul>`).join('');
  const defs = useDefinitions(use);
  const definitions = defs.length
    ? `<details class="law-text"><summary>용도의 법적 정의</summary><ul>${defs.map((d) => `<li><b>${escape(d.name)}</b>${d.law ? ` <span class="muted">${escape(d.law)}</span>` : ''}${d.definition ? `<br>${escape(d.definition)}` : ''}</li>`).join('')}</ul></details>` : '';
  return `<section class="doc-section use-card">${head}${zones}${definitions}</section>`;
}

function usesTab(name) {
  const notYet = siteNotYet(name);
  if (notYet) return notYet;
  const u = ui.useFind;
  const busy = Boolean(u.busy);
  const candidates = u.candidates?.length
    ? `<section class="use-candidates" aria-labelledby="use-candidates-title"><h2 id="use-candidates-title">토지이음 용도 이름 ${u.candidates.length}개</h2>
      <p class="muted small-text">고르면 이 대지의 용도지역·지구마다 지을 수 있는지 조회해 저장합니다.</p>
      <ul>${u.candidates.map((c) => `<li><button type="button" class="secondary small" data-action="use-check" data-use="${escape(c.name)}" ${busy ? 'disabled' : ''}>${escape(c.name)}</button></li>`).join('')}</ul></section>` : '';
  const working = u.busy === 'search' ? '이름을 찾는 중입니다.' : u.busy.startsWith('check:') ? `${u.busy.slice(6)}을(를) 정부 데이터에서 확인하는 중입니다.` : '';
  const error = u.error
    ? `<p class="error-text" role="alert">${escape(u.error)}${u.errorStatus === 503 ? ' <button type="button" class="secondary small" data-action="settings">설정 열기</button>' : ''}</p>` : '';
  const uses = ui.site.uses || [];
  return `<form class="site-form" id="use-form" novalidate>
      <label for="use-query">지으려는 용도</label>
      <div class="address-row"><input id="use-query" data-focus="use-query" maxlength="50" placeholder="예: 공장, 단독주택, 미술관" value="${escape(u.query)}" autocomplete="off">
        <button class="primary small" type="submit" ${busy ? 'disabled' : ''}>이름 찾기</button></div>
      <p class="muted small-text">토지이음의 용도 이름과 정확히 같아야 조회됩니다. 이름 일부로 찾은 뒤 고르세요.</p></form>
    ${working ? `<p class="working" role="status"><span class="spinner" aria-hidden="true"></span>${escape(working)}</p>` : ''}${error}${candidates}
    ${uses.length ? uses.map(useCard).join('') : '<p class="muted">아직 조회한 용도가 없습니다.</p>'}
    <p class="muted small-text">결과는 토지이음의 판단(가능·금지 등)을 그대로 보여 줍니다. "금지"여도 단서 조항으로 허용될 수 있으니 단서를 함께 확인하세요. 대지를 다시 조회하면 저장한 용도도 새 용도지역으로 다시 확인합니다.</p>`;
}

export function sitePage(name) {
  const tab = currentRoute.tab;
  const site = ui.site;
  const meta = site?.available
    ? `${escape(siteHeadline(site))}${site.fetched_at ? ` · 조회 ${escape(dateTime(site.fetched_at))}` : ''}`
    : '아직 조회하지 않았습니다';
  const tabs = [
    ['facts', '대지 사실', sitePath(name)], ['ordinance', '조례', sitePath(name, 'ordinance')],
    ['uses', '계획 용도', sitePath(name, 'uses')], ['find', '찾기', sitePath(name, 'find')],
  ];
  return `<section class="expert-page site-page" aria-label="대지">
    <header class="expert-head"><div><h1>대지</h1><p class="expert-meta">${meta}</p></div>
      <a class="icon-button" href="${projectUrl(name)}" aria-label="대지 화면 닫기">×</a></header>
    <nav class="expert-tabs" aria-label="대지 화면">
      ${tabs.map(([id, label, href]) => `<a class="tab ${id === tab ? 'active' : ''}" href="${href}" ${id === tab ? 'aria-current="page"' : ''}>${label}</a>`).join('')}
    </nav>
    <div class="content-scroll" data-scroll="site:${tab}" data-scroll-from="top">${siteReaderBar(name, tab)}${siteTab(name, tab)}</div>
  </section>`;
}

// The site reader from the site page: run it on the saved site, or say it waits for one.
function siteReaderBar(name, tab) {
  const expert = expertById('site_reader');
  if (!expert) return '';
  const busy = jobRunning();
  if (ui.siteFirst && tab === 'find') {
    return `<div class="site-run waiting"><p>대지 분석가는 저장한 대지 사실로 실행합니다. 필지를 찾아 저장하면 바로 실행합니다.</p>
      <button class="secondary small" data-action="run-expert" data-agent="site_reader" data-without-site="true" ${busy ? 'disabled' : ''}>대지 없이 브리프로 실행</button></div>`;
  }
  if (!ui.site?.available) return '';
  if (expertStatus(expert, ui.job) === 'running') {
    return `<div class="site-run"><p class="working" role="status"><span class="spinner" aria-hidden="true"></span><b>대지 분석가</b> · 실행 중입니다. 결과는 제도판의 AI 섹션에 놓입니다.</p></div>`;
  }
  return `<div class="site-run"><p><b>대지 분석가</b> · ${expert.done ? `결과 있음 <a href="${expertPath(name, 'site_reader')}">결과 보기</a>` : '아직 실행 전'}</p>
    <button class="secondary small" data-action="run-expert" data-agent="site_reader" ${busy ? 'disabled' : ''}>${expert.done ? '다시 실행' : '실행'}</button></div>`;
}

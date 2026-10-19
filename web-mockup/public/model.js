export const STORAGE_KEY = 'sida-ui-mockup-v1';

export const EXPERTS = [
  ['11', '대지 분석가', '대지 분석'],
  ['12', '프로그램 분석가', '프로그램 분석'],
  ['13', '법규 검토자', '법규 검토'],
  ['14', '선례 연구자', '선례 연구'],
  ['21', '개념 정리자', '개념 정리'],
  ['31', '조건·의사결정 정리자', '조건·의사결정'],
  ['41', '공간 검토자', '공간 검토'],
  ['42', '시스템 자문가', '시스템 검토'],
  ['51', '설계 비평가', '설계 비평'],
  ['61', '표현 계획자', '표현 계획'],
  ['62', '발표 편집자', '발표 편집'],
];

export function initialState() {
  return {
    version: 1,
    projects: [
      { id: 'museum', name: '뮤지엄', description: '', type: '미술관', phase: '개념 발전', summary: '4 결정 사항 · 2 개 미결정', updated: 5, date: '오늘 마지막으로 열람' },
      { id: 'housing', name: '주거 공간 연구', description: '', type: '개인 주택', phase: '대지 분석', summary: '3 개 분석 · 1 개 미해결 질문', updated: 4, date: '어제 수정' },
      { id: 'installation', name: '공간 설치 작업', description: '', type: '설치 작업', phase: '디자인 리서치', summary: '개념 발전 중', updated: 3, date: '10월 10' },
      { id: 'library', name: '커뮤니티 도서관', description: '', type: '공공건축', phase: '프로그램 구성', summary: '2 개 분석 · 3 개 미결정', updated: 2, date: '10월 06' },
      { id: 'pavilion', name: '임시 파빌리온', description: '', type: '파빌리온', phase: '초기 탐색', summary: '설계 초기 단계', updated: 1, date: '9월 29' },
    ],
    messages: {},
    threads: {},
  };
}

export function restoreState(raw) {
  try {
    const state = JSON.parse(raw);
    const validProject = (p) => p && typeof p.id === 'string' && /^[a-z0-9-]+$/.test(p.id)
      && ['name', 'description', 'type', 'phase', 'summary', 'date'].every((k) => typeof p[k] === 'string')
      && Number.isFinite(p.updated);
    const validMap = (map, validate) => map && typeof map === 'object' && !Array.isArray(map)
      && Object.entries(map).every(([key, list]) => /^[a-z0-9:-]+$/.test(key)
        && Array.isArray(list) && list.every(validate));
    if (state?.version !== 1 || !Array.isArray(state.projects)
      || !state.projects.every(validProject)
      || new Set(state.projects.map((p) => p.id)).size !== state.projects.length
      || !validMap(state.messages, (m) => m && ['user', 'assistant'].includes(m.role)
        && typeof m.text === 'string' && Array.isArray(m.files) && m.files.every((f) => typeof f === 'string'))
      || !validMap(state.threads, (t) => t && /^\d+$/.test(t.id) && typeof t.title === 'string')) {
      return initialState();
    }
    return state;
  } catch {
    return initialState();
  }
}

export function findProjects(projects, query = '', sort = 'recent') {
  const term = query.trim().toLocaleLowerCase('ko');
  return projects.filter((p) => `${p.name} ${p.type} ${p.phase}`.toLocaleLowerCase('ko').includes(term))
    .sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name, 'ko') : b.updated - a.updated);
}

export function addProject(state, name, description = '', id = `project-${crypto.randomUUID()}`) {
  const cleanName = name.trim();
  if (!cleanName || cleanName.length > 80) throw new Error('프로젝트 이름을 1~80자로 입력해 주세요.');
  const project = {
    id, name: cleanName, description: description.trim().slice(0, 2000),
    type: '건축 설계', phase: '초기 탐색', summary: '설계 초기 단계',
    updated: Date.now(), date: '방금 생성',
  };
  state.projects.unshift(project);
  return project;
}

export function deleteProject(state, projectId) {
  const index = state.projects.findIndex((project) => project.id === projectId);
  if (index < 0) return false;
  state.projects.splice(index, 1);
  for (const collection of [state.messages, state.threads]) {
    for (const key of Object.keys(collection)) {
      if (key.startsWith(`${projectId}:`)) delete collection[key];
    }
  }
  return true;
}

export function threadList(state, projectId, expertId) {
  const key = `${projectId}:${expertId}`;
  if (!Object.hasOwn(state.threads, key)) {
    const expert = EXPERTS.find(([id]) => id === expertId);
    state.threads[key] = [{ id: '01', title: `${expert[2]} 01` }, { id: '02', title: `${expert[2]} 02` }];
  }
  return state.threads[key];
}

export function addThread(state, projectId, expertId) {
  const threads = threadList(state, projectId, expertId);
  const id = String(Math.max(...threads.map((t) => Number(t.id)), 0) + 1).padStart(2, '0');
  const expert = EXPERTS.find(([code]) => code === expertId);
  const thread = { id, title: `${expert[2]} ${id}` };
  threads.push(thread);
  return thread;
}

export function messageKey(projectId, expertId = '', threadId = '01') {
  return `${projectId}:${expertId || 'main'}:${threadId}`;
}

export function sendMessage(state, key, text, files = []) {
  const cleanText = text.trim().slice(0, 6000);
  if (!cleanText && !files.length) return false;
  if (!Object.hasOwn(state.messages, key)) state.messages[key] = [];
  state.messages[key].push({ role: 'user', text: cleanText, files: [...files] });
  state.messages[key].push({
    role: 'assistant',
    text: '샘플 응답입니다. 설계 의도와 검증할 조건을 구분해 살펴보세요. 평면과 단면에서 확인할 지점을 정리하며 다음 대화를 이어갈 수 있습니다.',
    files: [],
  });
  return true;
}

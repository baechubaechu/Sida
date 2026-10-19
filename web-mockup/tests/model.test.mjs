import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initialState, restoreState, findProjects, addProject, deleteProject, threadList, addThread, messageKey, sendMessage } from '../public/model.js';

test('sample projects are independent copies and preserve Figma labels', () => {
  const first = initialState();
  first.projects[0].name = 'changed';
  assert.equal(initialState().projects[0].name, '뮤지엄');
  assert.equal(initialState().projects.length, 5);
});

test('search trims whitespace and includes metadata; missing queries return no results', () => {
  const projects = initialState().projects;
  assert.equal(findProjects(projects, '  주거  ')[0].id, 'housing');
  assert.equal(findProjects(projects, '미술관')[0].id, 'museum');
  assert.equal(findProjects(projects, '초기 탐색')[0].id, 'pavilion');
  assert.deepEqual(findProjects(projects, '없는 이름'), []);
});

test('sorting preserves the stored order', () => {
  const state = initialState();
  const before = structuredClone(state.projects);
  assert.equal(findProjects(state.projects, '', 'name')[0].name, '공간 설치 작업');
  assert.equal(findProjects(state.projects)[0].id, 'museum');
  assert.deepEqual(state.projects, before);
});

test('creating a project trims input and retains description', () => {
  const state = initialState();
  const project = addProject(state, '  새 미술관  ', '  보이드 연구  ', 'project-test');
  assert.equal(project.name, '새 미술관');
  assert.equal(project.description, '보이드 연구');
  assert.equal(findProjects(state.projects)[0], project);
  assert.equal(state.projects.length, 6);
});

test('blank and overlong names do not create projects', () => {
  const state = initialState();
  for (const name of ['', '   ', '가'.repeat(81)]) assert.throws(() => addProject(state, name));
  assert.equal(state.projects.length, 5);
});

test('empty messages are ignored; attachment-only messages work', () => {
  const state = initialState();
  const key = messageKey('museum');
  assert.equal(sendMessage(state, key, '   '), false);
  assert.equal(state.messages[key], undefined);
  assert.equal(sendMessage(state, key, '', ['plan.pdf']), true);
  assert.deepEqual(state.messages[key][0].files, ['plan.pdf']);
  assert.match(state.messages[key][1].text, /샘플 응답/);
});

test('messages remain isolated by project, expert and thread', () => {
  const state = initialState();
  const keys = [messageKey('museum'), messageKey('housing'), messageKey('museum', '', '02'), messageKey('museum', '41', '01'), messageKey('museum', '41', '02'), messageKey('museum', '11', '01')];
  keys.forEach((key, i) => sendMessage(state, key, `메시지 ${i}`));
  assert.equal(new Set(keys).size, 6);
  keys.forEach((key, i) => {
    assert.equal(state.messages[key].length, 2);
    assert.equal(state.messages[key][0].text, `메시지 ${i}`);
  });
});

test('attachments are copied and message length is bounded', () => {
  const state = initialState();
  const files = ['plan.pdf'];
  sendMessage(state, 'museum:main:01', '가'.repeat(7000), files);
  files.push('other.pdf');
  assert.equal(state.messages['museum:main:01'][0].text.length, 6000);
  assert.deepEqual(state.messages['museum:main:01'][0].files, ['plan.pdf']);
});

test('new expert threads have unique ids and project-specific history', () => {
  const state = initialState();
  assert.equal(threadList(state, 'museum', '41')[0].title, '공간 검토 01');
  assert.equal(addThread(state, 'museum', '41').id, '03');
  assert.equal(addThread(state, 'museum', '41').id, '04');
  assert.equal(threadList(state, 'housing', '41').length, 2);
  assert.equal(threadList(state, 'museum', '11').length, 2);
});

test('project, messages and threads survive storage round trip', () => {
  const state = initialState();
  addProject(state, '새 프로젝트', '', 'project-test');
  const thread = addThread(state, 'museum', '41');
  sendMessage(state, messageKey('museum', '41', thread.id), '<script>사용자 텍스트</script>', ['a.pdf']);
  assert.deepEqual(restoreState(JSON.stringify(state)), state);
});

test('invalid, outdated and unexpected stored data resets safely', () => {
  for (const raw of [null, '', '{', 'null', '{}', '[]', '{"version":0}']) assert.deepEqual(restoreState(raw), initialState());
  const invalid = initialState();
  invalid.messages['museum:main:01'] = [{ role: 'user', text: 42, files: [] }];
  assert.deepEqual(restoreState(JSON.stringify(invalid)), initialState());
  const duplicate = initialState();
  duplicate.projects.push(duplicate.projects[0]);
  assert.deepEqual(restoreState(JSON.stringify(duplicate)), initialState());
});

test('deleting a project removes its main and expert history without touching other projects', () => {
  const state = initialState();
  addProject(state, '이름이 비슷한 프로젝트', '', 'museum-annex');
  for (const id of ['museum', 'museum-annex', 'housing']) {
    sendMessage(state, messageKey(id), `${id} 대화`);
    sendMessage(state, messageKey(id, '41', '02'), `${id} 분석`);
    threadList(state, id, '41');
    state.threads[`${id}:main`] = [{ id: '01', title: '메인 채팅' }];
  }
  const otherMessages = structuredClone(state.messages['museum-annex:main:01']);
  assert.equal(deleteProject(state, 'museum'), true);
  assert.equal(state.projects.some((p) => p.id === 'museum'), false);
  assert.equal(Object.keys(state.messages).some((key) => key.startsWith('museum:')), false);
  assert.equal(Object.keys(state.threads).some((key) => key.startsWith('museum:')), false);
  assert.deepEqual(state.messages['museum-annex:main:01'], otherMessages);
  assert.equal(state.threads['housing:41'].length, 2);
  assert.deepEqual(restoreState(JSON.stringify(state)), state);
});

test('deleting a missing project is a no-op', () => {
  const state = initialState();
  const before = structuredClone(state);
  assert.equal(deleteProject(state, 'missing'), false);
  assert.deepEqual(state, before);
});

test('deleting every project persists an empty list instead of resurrecting samples', () => {
  const state = initialState();
  for (const project of [...state.projects]) deleteProject(state, project.id);
  assert.deepEqual(state.projects, []);
  assert.deepEqual(restoreState(JSON.stringify(state)), state);
  addProject(state, '다시 시작', '', 'project-restart');
  assert.equal(state.projects.length, 1);
  assert.equal(state.projects[0].name, '다시 시작');
});

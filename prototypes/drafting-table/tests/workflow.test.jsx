import { createRoot } from 'react-dom/client';
import { DraftingTableApp } from '../src/table/App.jsx';
import '../src/shared/styles.css';
import '../src/table/table.css';

const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
const ready = async (predicate) => {
  const deadline = performance.now() + 5000;
  while (!predicate()) { if (performance.now() > deadline) throw new Error('화면 준비 시간 초과'); await frame(); }
};
const results = [];
const check = (condition, message) => {
  if (!condition) throw new Error(message);
  results.push(message);
};
const byLabel = (label) => document.querySelector(`[aria-label="${label}"]`);
const buttonText = (text) => [...document.querySelectorAll('button')].find((button) => button.textContent.trim() === text);
const click = async (element) => { if (!element) throw new Error('테스트 대상 없음'); element.click(); await frame(); };
const paper = (id) => document.querySelector(`.table-css [data-paper="${id}"]`);
const input = async (element, value) => {
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(element, value);
  element.dispatchEvent(new Event('input', { bubbles: true }));
  await frame();
};
const key = async (value, options = {}) => {
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true, ...options }));
  await frame();
};

createRoot(document.getElementById('root')).render(<DraftingTableApp />);

async function run() {
  await frame();
  await ready(() => byLabel('안 A · 판상형 상세 보기'));
  check(byLabel('실행 취소').disabled, '초기에는 실행 취소 비활성');
  await click(byLabel('안 A · 판상형 상세 보기'));
  check(document.querySelector('dialog[open]')?.textContent.includes('30.8%'), '축척과 무관한 상세 창에서 실제 카드 수치 표시');
  await click(buttonText('이 카드로 질문하기 →'));
  check(!document.querySelector('dialog[open]') && document.querySelectorAll('.attachment').length === 1, '상세 카드가 질문 자료로 연결');
  check(document.activeElement === document.getElementById('ask'), '질문하기 후 입력창에 초점');
  await click(byLabel('안 A · 판상형 질문 자료에서 빼기'));
  check(document.querySelectorAll('.attachment').length === 0, '자료 개별 해제와 보드 선택 동기화');
  await click(buttonText('매스안 선택'));
  check(document.querySelectorAll('.attachment').length === 2 && document.querySelectorAll('.paper.is-selected').length === 2, '두 매스안 선택이 보드와 입력창에 표시');
  await click(buttonText('두 안 비교 질문 →'));
  check(document.getElementById('ask').value.includes('선택한 두 매스안') && document.querySelectorAll('.msg.user').length === 0, '비교 버튼은 초안만 채우며 자동 전송하지 않음');
  await click(byLabel('보내기'));
  check(document.querySelector('.msg.user .chips').textContent.includes('안 A') && document.querySelector('.msg.user .chips').textContent.includes('안 B'), '보낸 메시지에 참조 자료 이름 기록');
  await click(byLabel('안 A · 판상형 질문 자료에서 빼기'));
  check(document.querySelector('.msg.user .chips').textContent.includes('안 A'), '선택을 바꿔도 이미 보낸 질문의 자료 기록 유지');
  await click(byLabel('선택 모두 해제'));
  // Real note editing: focus groups successive text edits into one undo step.
  paper('note-1').focus();
  paper('note-1').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  await frame();
  const note = byLabel('상세 메모 내용');
  const original = note.value;
  note.focus();
  await input(note, '메모 수정 1');
  await input(note, '메모 수정 완료');
  await click(byLabel('상세 보기 닫기'));
  await click(byLabel('실행 취소'));
  check(paper('note-1').textContent === original, '여러 글자 메모 편집을 한 번에 실행 취소');
  await click(byLabel('다시 실행'));
  check(paper('note-1').textContent === '메모 수정 완료', '메모 편집 다시 실행');
  await click(buttonText('트레이싱지 덮기'));
  const tracing = document.querySelector('.table-css .kind-tracing');
  check(tracing && !byLabel('실행 취소').disabled, '트레이싱 추가가 기록됨');
  await key('z', { ctrlKey: true });
  check(!document.querySelector('.table-css .kind-tracing'), 'Ctrl+Z로 트레이싱 추가 취소');
  await key('z', { metaKey: true, shiftKey: true });
  check(document.querySelector('.table-css .kind-tracing'), 'Cmd+Shift+Z로 트레이싱 복원');
  await click(buttonText('매스안 선택'));
  await click(buttonText('삭제'));
  check(!paper('mass-a') && !paper('mass-b') && paper('site'), '선택 삭제는 대지 자료를 보존');
  await click(byLabel('실행 취소'));
  check(paper('mass-a') && paper('mass-b'), '두 카드 삭제를 한 번에 복원');
  await click(buttonText('트레이싱지 덮기')); // Already overlaid: no document edit.
  check(!byLabel('다시 실행').disabled, '이미 덮인 트레이싱 선택은 다시 실행 기록을 지우지 않음');
  check(!document.querySelector('dialog[open]'), '복원 후 불필요한 상세 창이 열리지 않음');
}

run().then(() => {
  document.title = `PASS · ${results.length} workflow checks`;
  const report = document.createElement('pre');
  report.id = 'test-report';
  report.textContent = `PASS\n${results.map((result) => `✓ ${result}`).join('\n')}`;
  report.style.cssText = 'position:fixed;inset:12px;z-index:9999;background:white;padding:24px;overflow:auto;white-space:pre-wrap';
  document.body.append(report);
}).catch((error) => {
  document.title = 'FAIL · Workflow';
  const report = document.createElement('pre');
  report.id = 'test-report';
  report.textContent = `FAIL\n${error.message}\n${results.join('\n')}`;
  report.style.cssText = 'position:fixed;inset:12px;z-index:9999;background:white;padding:24px;overflow:auto';
  document.body.append(report);
  console.error(error);
});

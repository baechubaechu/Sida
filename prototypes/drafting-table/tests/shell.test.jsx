// Real browser regression checks; no backend or model calls.
import { createRoot } from 'react-dom/client';
import { Shell } from '../src/shared/Shell.jsx';
import '../src/shared/styles.css';

const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
const results = [];
const check = (condition, message) => {
  if (!condition) throw new Error(message);
  results.push(message);
};
const button = (label) => document.querySelector(`button[aria-label="${label}"]`);
const boardWidth = () => document.querySelector('.board').getBoundingClientRect().width;
const visible = (selector) => getComputedStyle(document.querySelector(selector)).display !== 'none';
const click = async (element) => { element.click(); await frame(); };

createRoot(document.getElementById('root')).render(
  <Shell library="테스트" selection={[]} addCard={() => {}} focusCard={() => {}} board={<p>제도판 테스트</p>} />,
);

async function run() {
  await frame();
  check(innerWidth > 900, '데스크톱 뷰포트에서 실행');
  check(!document.querySelector('.rail'), '가장 왼쪽 내비게이션 바 제거');
  const original = boardWidth();
  const panel = document.getElementById('experts-panel');
  const draft = document.getElementById('ask');
  draft.focus();
  const toggle = button('전문가 접기');
  check(toggle.getAttribute('aria-controls') === panel.id && toggle.getAttribute('aria-expanded') === 'true', '토글과 전문가 패널의 접근성 연결');
  await click(toggle);
  const expertsClosed = boardWidth();
  check(!visible('.experts') && expertsClosed > original + 200, '전문가를 접으면 숨겨지고 제도판이 넓어짐');
  check(button('전문가 펼치기').getAttribute('aria-expanded') === 'false', '접힌 상태 접근성 표시');
  await click(button('Conductor 접기'));
  check(boardWidth() > expertsClosed + 250, '양쪽 패널을 모두 접을 수 있음');
  await click(button('전문가 펼치기'));
  check(visible('.experts') && !visible('section.conductor'), '전문가와 대화 패널을 독립적으로 펼침');
  check(document.getElementById('experts-panel') === panel && document.getElementById('ask') === draft, '패널 전환 시 대화와 전문가 DOM 유지');
  await click(button('Conductor 펼치기'));
  check(Math.abs(boardWidth() - original) < 1, '두 패널을 펼치면 원래 제도판 폭 복원');
  await click(document.querySelector('.expert-list button'));
  await click(button('전문가 패널 닫기'));
  await click(button('전문가 펼치기'));
  check(document.querySelector('.expert-list button').disabled && document.querySelector('.run'), '접었다 펼쳐도 진행 중인 전문가 검토 유지');
}

run().then(() => {
  document.title = `PASS · ${results.length} checks`;
  const report = document.createElement('pre');
  report.id = 'test-report';
  report.textContent = `PASS\n${results.map((result) => `✓ ${result}`).join('\n')}`;
  document.querySelector('.board-canvas').replaceChildren(report);
}).catch((error) => {
  document.title = 'FAIL · Shell UI';
  const report = document.createElement('pre');
  report.id = 'test-report';
  report.textContent = `FAIL\n${error.message}\n${results.join('\n')}`;
  document.body.replaceChildren(report);
  console.error(error);
});

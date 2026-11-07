// Project list actions: the info dialog, deleting, the sample project.

import { escapeHtml as escape, projectPath as projectUrl } from './model.js';
import { api, projectApi } from './api.js';
import { loadProjects } from './jobs.js';
import { render } from './render.js';
import { announce, currentProjectLabel, currentRoute, deleteConfirm, deleteDialog, deleteError, openingTried, projectInfoBody, projectInfoDialog, toast, ui } from './state.js';

let projectInfoEdit = null;

export async function openProjectInfo(name) {
  projectInfoEdit = null;
  projectInfoBody.innerHTML = '<p role="status">프로젝트 정보를 불러오는 중입니다.</p>';
  projectInfoDialog.showModal();
  try {
    const info = await api(`${projectApi(name)}/info`);
    if (!projectInfoDialog.open) return;
    projectInfoEdit = { name, ...info };
    projectInfoBody.innerHTML = `<label for="edit-project-name">프로젝트 이름</label><input id="edit-project-name" name="display_name" value="${escape(info.display_name)}" maxlength="80" required>
      <label for="edit-project-type">프로젝트 유형</label><input id="edit-project-type" name="type" value="${escape(info.type)}" maxlength="80">
      <label for="edit-project-description">설명 · 설계 의도</label><textarea id="edit-project-description" name="description" rows="6" maxlength="6000">${escape(info.description)}</textarea>
      <p class="muted small-text">대지 필지는 프로젝트의 대지 화면에서 수정할 수 있습니다.</p>
      <p class="form-error error-text" role="alert"></p>
      <div class="form-actions"><button type="button" class="secondary" id="project-info-cancel">취소</button><button type="submit" class="primary">저장</button></div>`;
    projectInfoBody.querySelector('input').focus();
  } catch (error) {
    projectInfoBody.innerHTML = `<p class="error-text" role="alert">${escape(error.message)}</p>`;
  }
}

document.querySelector('#project-info-close').addEventListener('click', () => projectInfoDialog.close());
projectInfoBody.addEventListener('click', event => { if (event.target.id === 'project-info-cancel') projectInfoDialog.close(); });
document.querySelector('#project-info-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!projectInfoEdit) return;
  const form = event.target;
  const saved = projectInfoEdit;
  const button = form.querySelector('[type="submit"]');
  if (button.disabled) return;
  button.disabled = true;
  const fields = Object.fromEntries(['display_name', 'type', 'description'].map(key => [key, form.elements[key].value]));
  try {
    await api(`${projectApi(saved.name)}/info`, { method: 'PATCH', body: { fields, expected_revision: saved.revision } });
    projectInfoDialog.close();
    await loadProjects();
    render(false);
    toast('프로젝트 정보를 저장했습니다.', 'success');
  } catch (error) {
    form.querySelector('[role="alert"]').textContent = error.message;
    button.disabled = false;
  }
});

export function askDelete(name) {
  deleteDialog.dataset.project = name;
  deleteDialog.querySelector('#delete-text').textContent = `‘${currentProjectLabel(name)}’ 프로젝트를 삭제할까요? 브리프, Conductor 대화, 전문가 결과와 채팅, 제도판, 대지 정보가 모두 지워지며 되돌릴 수 없습니다.`;
  deleteError.textContent = '';
  deleteConfirm.disabled = false;
  deleteDialog.showModal();
}

async function deleteProject() {
  const name = deleteDialog.dataset.project;
  deleteConfirm.disabled = true;
  deleteError.textContent = '';
  try {
    await api(projectApi(name), { method: 'DELETE' });
  } catch (error) {
    deleteError.textContent = error.message;
    deleteConfirm.disabled = false;
    if (error.status !== 404) return;
  }
  deleteDialog.close();
  openingTried.delete(name);
  if (ui.projects) ui.projects = ui.projects.filter((p) => p.name !== name);
  toast(`‘${name}’ 프로젝트를 삭제했습니다.`, 'success');
  announce(`${name} 프로젝트를 삭제했습니다.`);
  if (currentRoute.page === 'project' && currentRoute.name === name) location.hash = '#/';
  else render(false);
  loadProjects().then(() => render(false));
}

export async function createSample() {
  try {
    const { project } = await api('/api/projects/sample', { method: 'POST' });
    await loadProjects();
    location.hash = projectUrl(project.name);
  } catch (error) {
    toast(error.message, 'error');
  }
}

deleteConfirm.addEventListener('click', deleteProject);

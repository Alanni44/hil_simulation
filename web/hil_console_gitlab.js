(function () {
  'use strict';
  var api = new HilApi();
  var stagedRequest = null;
  var elements = {};
  function byId(id) { return document.getElementById(id); }
  function log(value) { elements.log.textContent += '\n' + value; elements.log.scrollTop = elements.log.scrollHeight; }
  function setStatus(value, bad) { elements.status.textContent = value; elements.status.style.color = bad ? '#b93434' : '#168c46'; }
  function fail(error) { var message = error && error.message ? error.message : String(error); setStatus(message, true); log('失败：' + message); }
  function request(cmd, params) { return api.request(cmd, params).then(function (reply) { if (reply.status === 'FAILED' || reply.status === 'error') { throw new Error(reply.message || '服务拒绝了请求。'); } return reply; }); }
  function selectedTag() { return elements.release.value; }
  function renderReleases(releases) {
    elements.release.textContent = '';
    elements.releaseRows.textContent = '';
    releases.forEach(function (release, index) {
      var option = document.createElement('option'); option.value = release.tag_name; option.textContent = release.tag_name; elements.release.appendChild(option);
      var row = document.createElement('tr'); if (index === 0) { row.className = 'selected'; }
      [release.tag_name, release.commit_id || '-', release.released_at || '-', release.asset_name || '-'].forEach(function (value) { var cell = document.createElement('td'); cell.textContent = value; row.appendChild(cell); });
      elements.releaseRows.appendChild(row);
    });
    elements.release.disabled = releases.length === 0;
    elements.stage.disabled = releases.length === 0;
  }
  function refreshStatus() {
    return request('gitlab_status', {}).then(function (reply) {
      var state = reply.gitlab; setStatus(state.code + '：' + state.message, !state.configured); log('GitLab 状态：' + state.code);
      elements.refresh.disabled = !state.configured;
      elements.project.disabled = !state.configured;
      if (!state.configured) { elements.release.disabled = true; elements.stage.disabled = true; }
      return state;
    });
  }
  function refreshHistory() { return request('gitlab_history', {}).then(function (reply) { elements.history.textContent = JSON.stringify(reply.events, null, 2); }); }
  function listReleases() {
    var project = elements.project.value.trim(); if (!project) { fail(new Error('请输入已批准的项目路径。')); return; }
    request('gitlab_list_releases', { project: project }).then(function (reply) { renderReleases(reply.releases); log('读取到 ' + reply.releases.length + ' 个发布版本。'); }).catch(fail);
  }
  function stage() {
    var project = elements.project.value.trim(); var tag = selectedTag();
    request('gitlab_stage_release', { request_id: 'web-' + Date.now(), project: project, tag_name: tag }).then(function (reply) {
      stagedRequest = reply.build_request; elements.build.disabled = false; elements.deploy.disabled = false;
      elements.stagedLabel.textContent = '已验证：' + reply.staged.model_ref + ' / ' + reply.staged.model_revision_ref;
      setStatus('READY：模型包已验证并暂存', false); log('暂存成功：' + reply.staged.package_sha256);
      return refreshHistory();
    }).catch(fail);
  }
  function build(operation) {
    if (!stagedRequest) { fail(new Error('请先验证并暂存模型包。')); return; }
    request(operation, stagedRequest).then(function (reply) { log(operation + '：' + reply.status); setStatus(reply.status, reply.status === 'FAILED'); }).catch(fail);
  }
  document.addEventListener('DOMContentLoaded', function () {
    elements = { url:byId('wsUrl'), connect:byId('connectBtn'), refresh:byId('refreshBtn'), project:byId('project'), release:byId('release'), stage:byId('stageBtn'), releaseRows:byId('releaseRows'), build:byId('buildBtn'), deploy:byId('deployBtn'), stagedLabel:byId('stagedLabel'), historyBtn:byId('historyBtn'), history:byId('history'), status:byId('status'), log:byId('log') };
    elements.connect.addEventListener('click', function () { api.connect(elements.url.value.trim()).then(function () { setStatus('已连接，正在读取 GitLab 配置…', false); log('WebSocket 已连接。'); return refreshStatus(); }).then(refreshHistory).catch(fail); });
    elements.refresh.addEventListener('click', listReleases); elements.stage.addEventListener('click', stage); elements.build.addEventListener('click', function () { build('build_package'); }); elements.deploy.addEventListener('click', function () { build('deploy_package'); }); elements.historyBtn.addEventListener('click', function () { refreshHistory().catch(fail); });
  });
}());

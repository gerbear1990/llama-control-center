// Extracts empty-state copy helpers from the shipped app.js.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'lcc_api', 'static', 'app.js'), 'utf8');
const start = src.indexOf('function profilesEmptyCopy');
if (start === -1) { console.log(JSON.stringify({ ok: false, error: 'profilesEmptyCopy not found' })); process.exit(1); }
const end = src.indexOf('\nfunction emptyStateHtml', start);
const fnSrc = src.slice(start, end === -1 ? undefined : end);
const ctx = {};
vm.createContext(ctx);
vm.runInContext(
  fnSrc + '; this.profilesEmptyCopy = profilesEmptyCopy; this.modelsEmptyCopy = modelsEmptyCopy; this.stageFirstRunCopy = stageFirstRunCopy; this.chatEmptyCopy = chatEmptyCopy; this.runtimesEmptyCopy = runtimesEmptyCopy;',
  ctx,
);

const cases = {
  noProfiles: ctx.profilesEmptyCopy(0, false, 0),
  modelsNoProfiles: ctx.profilesEmptyCopy(0, false, 3),
  filteredProfiles: ctx.profilesEmptyCopy(4, true, 3),
  populatedProfiles: ctx.profilesEmptyCopy(4, false, 3),
  noModels: ctx.modelsEmptyCopy(0, ''),
  searchedModels: ctx.modelsEmptyCopy(3, 'qwen'),
  unmatchedSearchNoQuery: ctx.modelsEmptyCopy(3, '   '),
  stageNoData: ctx.stageFirstRunCopy({ profileCount: 0, modelCount: 0, launchable: false }),
  stageModelsOnly: ctx.stageFirstRunCopy({ profileCount: 0, modelCount: 2, launchable: false }),
  stageReady: ctx.stageFirstRunCopy({ profileCount: 2, modelCount: 2, launchable: true }),
  chatIdle: ctx.chatEmptyCopy(false),
  chatRunning: ctx.chatEmptyCopy(true),
  chatRunningOnPort: ctx.chatEmptyCopy(true, { running: true, host: '127.0.0.1', port: 18100 }),
  runtimesNone: ctx.runtimesEmptyCopy(0, false),
  runtimesHidden: ctx.runtimesEmptyCopy(3, true),
};

const ok = (
  cases.noProfiles?.action === 'add-folders'
  && /No profiles yet/.test(cases.noProfiles.title)
  && cases.modelsNoProfiles?.action === 'goto-models'
  && cases.filteredProfiles?.action === 'clear-filters'
  && cases.populatedProfiles === null
  && cases.noModels?.action === 'add-folders'
  && cases.searchedModels?.action === 'clear-filters'
  && cases.searchedModels.title.includes('qwen')
  && cases.unmatchedSearchNoQuery?.action === 'clear-filters'
  && cases.stageNoData?.action === 'add-folders'
  && cases.stageModelsOnly?.action === 'goto-models'
  && cases.stageReady === null
  && cases.chatIdle?.action === 'goto-stage'
  && !cases.chatRunning.action
  && /18100/.test(cases.chatRunningOnPort.body)
  && cases.runtimesNone?.action === 'add-runtime-folders'
  && cases.runtimesHidden?.action === 'show-all-runtimes'
);

console.log(JSON.stringify({ ok, cases }));
process.exit(ok ? 0 : 1);

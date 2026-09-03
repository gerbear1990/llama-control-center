// Empty-state copy helpers, imported from the module that ships them.
//
// This used to slice the functions out of app.js by string offset. Importing
// real exports means a rename or a move fails here loudly, instead of the
// extraction quietly finding nothing.
(async () => {
  const {
    profilesEmptyCopy, modelsEmptyCopy, stageFirstRunCopy, chatEmptyCopy, runtimesEmptyCopy,
  } = await import('../lcc_api/static/js/copy.js');

  const cases = {
    noProfiles: profilesEmptyCopy(0, false, 0),
    modelsNoProfiles: profilesEmptyCopy(0, false, 3),
    filteredProfiles: profilesEmptyCopy(4, true, 3),
    populatedProfiles: profilesEmptyCopy(4, false, 3),
    noModels: modelsEmptyCopy(0, ''),
    searchedModels: modelsEmptyCopy(3, 'qwen'),
    unmatchedSearchNoQuery: modelsEmptyCopy(3, '   '),
    stageNoData: stageFirstRunCopy({ profileCount: 0, modelCount: 0, launchable: false }),
    stageModelsOnly: stageFirstRunCopy({ profileCount: 0, modelCount: 2, launchable: false }),
    stageReady: stageFirstRunCopy({ profileCount: 2, modelCount: 2, launchable: true }),
    chatIdle: chatEmptyCopy(false),
    chatRunning: chatEmptyCopy(true),
    chatRunningOnPort: chatEmptyCopy(true, { running: true, host: '127.0.0.1', port: 18100 }),
    runtimesNone: runtimesEmptyCopy(0, false),
    runtimesHidden: runtimesEmptyCopy(3, true),
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
})();

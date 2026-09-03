// Mutation handlers must not wait on a full dashboard refresh. That is the
// lag on Stop/Purge/Rename/Save: GitHub, HF CLI, and a model scan all block
// the paint. Targeted refreshResources() or a local apply*View is the rule.
const fs = require('fs');
const path = require('path');

const read = (rel) => fs.readFileSync(path.join(__dirname, '..', 'lcc_api/static', rel), 'utf8');

const mutationFiles = [
  'js/panels/servers.js',
  'js/panels/profiles.js',
  'js/panels/parameters.js',
  'js/panels/models.js',
  'js/panels/inventory.js',
  'js/panels/fit.js',
  'js/settings.js',
];

const offenders = mutationFiles.filter((rel) => read(rel).includes('await refresh()'));

const refreshSrc = read('js/refresh.js');
const hasTargeted = refreshSrc.includes('export async function refreshResources');
const coreFirst = refreshSrc.includes('background: true')
  && refreshSrc.includes('core.map')
  && !/await Promise\.all\(DASHBOARD_RESOURCES\.map/.test(refreshSrc);

const ok = offenders.length === 0 && hasTargeted && coreFirst;

console.log(JSON.stringify({ ok, offenders, hasTargeted, coreFirst }));
process.exit(ok ? 0 : 1);

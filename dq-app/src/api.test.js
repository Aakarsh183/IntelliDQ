import * as api from './api';

// App.js imports these by name; a rename or accidental deletion in api.js would
// otherwise only surface as a runtime "is not a function" in the browser.
const EXPECTED_EXPORTS = [
  'uploadFiles',
  'generateCode',
  'regenerateCode',
  'suggestColumns',
  'executeCode',
  'getMappings',
  'addRule',
  'recommendRules',
  'generateRemediation',
  'generateRemediationCode',
  'executeRemediation',
  'exportFailed',
  'enrichedRuleAPI',
  'suggestSchema',
  'exportFailedRemedies',
  'generateAllCodes',
  'ragQuery',
];

test('api module exports every call site App.js imports', () => {
  const missing = EXPECTED_EXPORTS.filter((name) => typeof api[name] !== 'function');
  expect(missing).toEqual([]);
});

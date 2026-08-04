// This file used to hold the Create React App boilerplate test, which rendered
// <App /> and asserted on the text "learn react" - text this app has not
// contained since App.js was written, so it failed on every run.
//
// Rendering the real App would need Monaco, axios and localStorage mocks. Import
// alone is still worth gating on: it exercises every import in a 2000-line
// component and catches syntax errors and broken module paths.
import App from './App';

test('App module loads and default-exports a component', () => {
  expect(typeof App).toBe('function');
});

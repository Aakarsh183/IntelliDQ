import React, { useState } from "react";
import Upload from "./components/Upload";

function App() {

  const [data, setData] = useState(null);

  return (
    <div style={{ padding: 20 }}>
      <h1>DQ Engine</h1>

      <Upload setData={setData} />

      {data && (
        <div>
          <h2>Dataset Columns</h2>
          <ul>
            {data.columns.map((col, i) => (
              <li key={i}>{col}</li>
            ))}
          </ul>

          <h2>Rules</h2>
          <ul>
            {data.rules.map((rule, i) => (
              <li key={i}>{rule.name}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default App;
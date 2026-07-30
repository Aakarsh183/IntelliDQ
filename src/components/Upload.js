import React, { useState } from "react";
import { uploadFiles } from "../api";

export default function Upload({ setData }) {

  const [dataset, setDataset] = useState(null);
  const [rules, setRules] = useState(null);

  const handleUpload = async () => {

    if (!dataset || !rules) {
      alert("Please upload both files");
      return;
    }

    const formData = new FormData();
    formData.append("dataset", dataset);
    formData.append("rules", rules);

    try {
      const res = await uploadFiles(formData);
      setData(res.data);
    } catch (err) {
      console.error(err);
      alert("Upload failed");
    }
  };

  return (
    <div>
      <h2>Upload Files</h2>

      <div>
        <p>Dataset File:</p>
        <input
          type="file"
          onChange={(e) => setDataset(e.target.files[0])}
        />
      </div>

      <div>
        <p>Rules File:</p>
        <input
          type="file"
          onChange={(e) => setRules(e.target.files[0])}
        />
      </div>

      <br />

      <button onClick={handleUpload}>
        Upload
      </button>
    </div>
  );
}
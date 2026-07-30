import axios from "axios";

const API = axios.create({
  baseURL: "http://localhost:8000",
});

export const uploadFiles = (formData) =>
  API.post("/upload", formData,{
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });

export const generateCode = (rule,weights) => {
  const session_id = localStorage.getItem("session_id");

  return API.post("/generate_code", {
    session_id,
    rule,
    weights
  });
};

export const regenerateCode = (rule, columns, weights) => {
  const session_id = localStorage.getItem("session_id");

  return API.post("/regenerate_code", {
    session_id,
    rule,
    columns,
    weights
  });
};

export const suggestColumns = (rule, weights) => {
  const session_id = localStorage.getItem("session_id");

  return API.post("/suggest_columns", {
    session_id,
    rule,
    weights
  });
};

export const executeCode = (pyspark_code,rule_name) => {
  const session_id = localStorage.getItem("session_id");

  return API.post("/execute_code", {
    session_id,
    pyspark_code,
    rule_name
  });
};

export const getMappings = (weights) => {
  const session_id = localStorage.getItem("session_id");

  return API.post("/get_mappings", {
    session_id,
    weights
  });
};

export const addRule = (rule) => {
  const session_id = localStorage.getItem("session_id");

  return API.post("/add_rule", {
    session_id,
    ...rule
  });
};

export const recommendRules = () => {
  const session_id = localStorage.getItem("session_id");

  return API.post("/recommend_rules", {
    session_id
  });
};

// Update generateRemediation to pass context from execResult
export const generateRemediation = (rule, failedIds, failedCount) => {
  const session_id = localStorage.getItem("session_id");
  return API.post("/generate_remediation", {
    session_id,
    rule, 
    failed_ids:   failedIds,     // ← NEW
    failed_count: failedCount,   // ← NEW
  });
};

// Update generateRemediationCode to pass failed_ids
export const generateRemediationCode = (logic, failedIds, rule = null, remediation = null) => {
  const session_id = localStorage.getItem("session_id");
  return API.post("/generate_remediation_code", {
    session_id,
    logic,
    rule,
    remediation,
    failed_ids: failedIds,       // ← NEW
  });
};

// executeRemediation — also pass failed_ids and logic for audit
export const executeRemediation = (code, failedIds, logic) => {
  const session_id = localStorage.getItem("session_id");
  return API.post("/execute_remediation", {
    session_id,
    pyspark_code: code,
    failed_ids:   failedIds,     // ← NEW
    logic,                       // ← NEW for audit log
  });
};

export const exportFailed = async (failedIds, ruleName) => {
  const session_id = localStorage.getItem("session_id");
  const response = await API.post(
    "/export_failed", {
     session_id,
     failed_ids: failedIds,
    }
  );
  console.log(response);
  // Trigger browser download
  const url      = window.URL.createObjectURL(new Blob([response.data]));
  const link     = document.createElement("a");
  link.href      = url;
  link.setAttribute("download", `${ruleName || "failed"}_records.csv`);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

export const enrichedRuleAPI = (newRule) => {
  const session_id = localStorage.getItem("session_id");

  return API.post("/enrich_rule",{
    session_id,
    newRule
  });
};

export const suggestSchema = () => {
  const session_id = localStorage.getItem("session_id");
  return API.post("/suggest_schema", { session_id });
};

export const exportFailedRemedies = async (ruleName) => {
  const session_id = localStorage.getItem("session_id");
  const response = await API.post(
    "/export_failed_remediations", {
      session_id,
    }
  );
  console.log(response);
  // Trigger browser download
  const url      = window.URL.createObjectURL(new Blob([response.data]));
  const link     = document.createElement("a");
  link.href      = url;
  link.setAttribute("download", `${ruleName || "failed"}_records.csv`);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

export const generateAllCodes = (weights) => {
  const session_id = localStorage.getItem("session_id");

  return API.post("/generate_all_codes", 
    { 
      session_id, 
      weights 
    });
};

export const ragQuery = (question, chatHistory = []) => {
  const session_id = localStorage.getItem("session_id");
  return API.post("/rag_query", {
    session_id,
    question,
    chat_history: chatHistory.slice(-6).map(m => ({   // last 3 turns
      role:    m.role,
      content: m.content,
    })),
  });
};

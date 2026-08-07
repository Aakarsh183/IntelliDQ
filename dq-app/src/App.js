import React, { useEffect, useState } from "react";
import Upload from "./components/Upload";
import {
  Container, Typography, Grid,
  Box, Slide, Button, Dialog, DialogTitle,
  DialogContent, Table, TableHead, TableRow,
  TableCell, TableBody, CircularProgress,
  Slider, Select, MenuItem, FormControl, InputLabel, Chip,
  TextField, IconButton, Checkbox, LinearProgress, Tooltip,
  Divider, Alert, Snackbar, Backdrop, Fade
} from "@mui/material";
import { createTheme, ThemeProvider, alpha, keyframes } from "@mui/material/styles";
import AddIcon           from "@mui/icons-material/Add";
import AutoAwesomeIcon   from "@mui/icons-material/AutoAwesome";
import CodeIcon          from "@mui/icons-material/Code";
import PlayArrowIcon     from "@mui/icons-material/PlayArrow";
import EditIcon          from "@mui/icons-material/Edit";
import ErrorIcon         from "@mui/icons-material/Error";
import CloseIcon         from "@mui/icons-material/Close";
import TuneIcon          from "@mui/icons-material/Tune";
import DatasetIcon       from "@mui/icons-material/Dataset";
import BarChartIcon      from "@mui/icons-material/BarChart";
import HourglassTopIcon  from "@mui/icons-material/HourglassTop";
import Editor            from "@monaco-editor/react";

import { generateCode, regenerateCode, suggestColumns, executeCode, getMappings, addRule, recommendRules, generateRemediation, generateRemediationCode, executeRemediation, exportFailed, enrichedRuleAPI, exportFailedRemedies, generateAllCodes, ragQuery } from "./api";


// ─── KEYFRAMES ────────────────────────────────────────────────────────────────
const pulse = keyframes`
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.4; }
`;
const scanline = keyframes`
  0%   { transform: translateY(-100%); }
  100% { transform: translateY(400%); }
`;
const spin = keyframes`
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
`;

// ─── THEME ────────────────────────────────────────────────────────────────────
const theme = createTheme({
  palette: {
    mode: "dark",
    primary:    { main: "#00D4FF" },
    secondary:  { main: "#7C3AED" },
    success:    { main: "#10B981" },
    error:      { main: "#EF4444" },
    warning:    { main: "#F59E0B" },
    background: { default: "#080C14", paper: "#0D1421" },
    text:       { primary: "#F1F5F9", secondary: "#64748B" },
  },
  typography: {
    fontFamily: "'DM Mono', 'Fira Code', monospace",
    h4:    { fontFamily: "'Syne', sans-serif", fontWeight: 800, letterSpacing: "-0.5px" },
    h5:    { fontFamily: "'Syne', sans-serif", fontWeight: 700 },
    h6:    { fontFamily: "'Syne', sans-serif", fontWeight: 600 },
    button:{ fontFamily: "'DM Mono', monospace", letterSpacing: "0.05em", textTransform: "none" },
  },
  shape: { borderRadius: 8 },
  components: {
    MuiDialog: {
      styleOverrides: {
        paper: { backgroundImage: "none", backgroundColor: "#0D1421", border: "1px solid #1E2D45" },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        head: {
          backgroundColor: "#080C14", color: "#00D4FF",
          fontFamily: "'DM Mono', monospace", fontSize: "0.7rem",
          letterSpacing: "0.12em", textTransform: "uppercase",
          borderBottom: "1px solid #1E2D45",
        },
        body: { borderBottom: "1px solid #111D2E", color: "#CBD5E1" },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: { "&:hover": { backgroundColor: "#111D2E" }, transition: "background 0.15s" },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: { borderRadius: 6, fontWeight: 500 },
        contained: {
          background: "linear-gradient(135deg, #00D4FF 0%, #0099CC 100%)",
          color: "#080C14", fontWeight: 700,
          "&:hover": { background: "linear-gradient(135deg, #33DDFF 0%, #00B8F0 100%)" },
        },
        outlined: {
          borderColor: "#1E2D45", color: "#94A3B8",
          "&:hover": { borderColor: "#00D4FF", color: "#00D4FF", backgroundColor: alpha("#00D4FF", 0.05) },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          backgroundColor: alpha("#00D4FF", 0.1), color: "#00D4FF",
          border: "1px solid " + alpha("#00D4FF", 0.25),
          fontFamily: "'DM Mono', monospace", fontSize: "0.7rem",
        },
      },
    },
    MuiSlider: {
      styleOverrides: {
        root:  { color: "#00D4FF" },
        rail:  { backgroundColor: "#1E2D45" },
        track: { background: "linear-gradient(90deg, #00D4FF, #7C3AED)" },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          "& .MuiOutlinedInput-root": {
            "& fieldset":         { borderColor: "#1E2D45" },
            "&:hover fieldset":   { borderColor: "#00D4FF" },
            "&.Mui-focused fieldset": { borderColor: "#00D4FF" },
            backgroundColor: "#080C14", fontFamily: "'DM Mono', monospace",
          },
          "& .MuiInputLabel-root.Mui-focused": { color: "#00D4FF" },
        },
      },
    },
    MuiSelect: {
      styleOverrides: {
        root: {
          "& .MuiOutlinedInput-notchedOutline": { borderColor: "#1E2D45" },
          backgroundColor: "#080C14",
        },
      },
    },
    MuiBackdrop: {
      styleOverrides: { root: { backdropFilter: "blur(4px)" } },
    },
  },
});

// ─── LOADING CONFIG ───────────────────────────────────────────────────────────
const LOADING_CONFIG = {
  addRule:        { message: "Saving Rule",           subtext: "Persisting rule to the engine…" },
  recommendRules: { message: "Analyzing Dataset",     subtext: "AI is scanning columns and patterns…" },
  saveAIRules:    { message: "Importing Rules",       subtext: "Adding selected rules to the engine…" },
  preloadMap:     { message: "Mapping Entities",      subtext: "Resolving column references via LLM + cosine…" },
  generateCode:   { message: "Generating PySpark",    subtext: "LLM is writing your validation query…" },
  executeCode:    { message: "Executing Query",       subtext: "Running PySpark against the dataset…" },
  regenerate:     { message: "Regenerating Code",     subtext: "Recompiling with updated mappings…" },
  suggestCols:    { message: "Suggesting Columns",    subtext: "Recalculating similarity weights…" },
  remediations:   { message: "Suggesting Remediations", subtext: "Generating Remediations for failed records..."},
  remediationCode: { message: "Generating code", subtext: "LLM is generating your remediation query..."},
  generateAll: {
    message: "Generating All Queries",
    subtext: "LLM is pre-computing PySpark code for all rules…"
  },
};

// ─── GLOBAL LOADING OVERLAY ───────────────────────────────────────────────────
function GlobalLoader({ open, message, subtext }) {
  return (
    <Backdrop open={open} sx={{ zIndex: 9999, background: "rgba(8,12,20,0.88)" }}>
      <Fade in={open}>
        <Box sx={{
          display: "flex", flexDirection: "column", alignItems: "center", gap: 3,
          p: 5,
          background: "#0D1421",
          border: "1px solid #1E2D45",
          borderRadius: 2,
          minWidth: 320,
          position: "relative",
          overflow: "hidden",
        }}>
          <Box sx={{
            position: "absolute", left: 0, right: 0, height: "35%",
            background: "linear-gradient(180deg, transparent, rgba(0,212,255,0.04), transparent)",
            animation: `${scanline} 2s linear infinite`,
            pointerEvents: "none",
          }} />
          <Box sx={{ position: "relative", width: 60, height: 60 }}>
            <Box sx={{ position: "absolute", inset: 0, borderRadius: "50%", border: "2px solid #1E2D45" }} />
            <Box sx={{
              position: "absolute", inset: 0, borderRadius: "50%",
              border: "2px solid transparent",
              borderTopColor: "#00D4FF",
              borderRightColor: alpha("#7C3AED", 0.5),
              animation: `${spin} 0.9s linear infinite`,
            }} />
            <Box sx={{
              position: "absolute", inset: 10, borderRadius: "50%",
              border: "1.5px solid transparent",
              borderTopColor: alpha("#00D4FF", 0.4),
              animation: `${spin} 1.6s linear infinite reverse`,
            }} />
            <Box sx={{
              position: "absolute", inset: 0,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <HourglassTopIcon sx={{ fontSize: 18, color: "#00D4FF", animation: `${pulse} 1.5s ease-in-out infinite` }} />
            </Box>
          </Box>
          <Box sx={{ textAlign: "center" }}>
            <Typography sx={{
              fontFamily: "'Syne', sans-serif", fontWeight: 700,
              fontSize: "1rem", color: "#F1F5F9", mb: 0.75,
            }}>
              {message}
            </Typography>
            {subtext && (
              <Typography sx={{
                fontFamily: "'DM Mono', monospace", fontSize: "0.7rem",
                color: "#475569", animation: `${pulse} 2s ease-in-out infinite`,
              }}>
                {subtext}
              </Typography>
            )}
          </Box>
          <LinearProgress sx={{
            width: "100%", height: 2, borderRadius: 1,
            backgroundColor: "#1E2D45",
            "& .MuiLinearProgress-bar": {
              background: "linear-gradient(90deg, #00D4FF, #7C3AED)",
              borderRadius: 1,
            },
          }} />
        </Box>
      </Fade>
    </Backdrop>
  );
}

// ─── INLINE ROW LOADER ────────────────────────────────────────────────────────
function InlineLoader({ label }) {
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
      <Box sx={{
        width: 14, height: 14, borderRadius: "50%",
        border: "1.5px solid transparent",
        borderTopColor: "#00D4FF",
        animation: `${spin} 0.8s linear infinite`,
        flexShrink: 0,
      }} />
      <Typography sx={{
        fontFamily: "'DM Mono', monospace", fontSize: "0.7rem",
        color: "#475569", animation: `${pulse} 1.5s ease-in-out infinite`,
      }}>
        {label}
      </Typography>
    </Box>
  );
}

// ─── SHARED UI ATOMS ──────────────────────────────────────────────────────────
const StatusDot = ({ active }) => (
  <Box component="span" sx={{
    display: "inline-block", width: 7, height: 7, borderRadius: "50%",
    backgroundColor: active ? "#10B981" : "#334155",
    boxShadow: active ? "0 0 8px #10B981" : "none", mr: 1,
  }} />
);

const SectionLabel = ({ children }) => (
  <Typography sx={{
    fontFamily: "'DM Mono', monospace", fontSize: "0.65rem",
    letterSpacing: "0.15em", textTransform: "uppercase", color: "#475569", mb: 1,
  }}>
    {children}
  </Typography>
);

const GlowCard = ({ children, sx = {}, ...props }) => (
  <Box sx={{
    background: "#0D1421", border: "1px solid #1E2D45", borderRadius: 2,
    p: 2.5, position: "relative", overflow: "hidden",
    "&::before": {
      content: '""', position: "absolute", top: 0, left: 0, right: 0, height: "1px",
      background: "linear-gradient(90deg, transparent, #00D4FF44, transparent)",
    },
    ...sx,
  }} {...props}>
    {children}
  </Box>
);

const MetricBadge = ({ label, value, color = "#00D4FF" }) => (
  <Box sx={{
    display: "flex", flexDirection: "column", alignItems: "center",
    px: 2, py: 1.5,
    background: alpha(color, 0.07), border: `1px solid ${alpha(color, 0.2)}`, borderRadius: 2,
    minWidth: 80,
  }}>
    <Typography sx={{ fontSize: "1.4rem", fontWeight: 800, color, lineHeight: 1, fontFamily: "'Syne', sans-serif" }}>
      {value}
    </Typography>
    <Typography sx={{ fontSize: "0.6rem", color: "#475569", mt: 0.5, letterSpacing: "0.1em", textTransform: "uppercase" }}>
      {label}
    </Typography>
  </Box>
);

const WeightBar = ({ label, value, onChange, onCommit, color }) => (
  <Box sx={{ mb: 2.5 }}>
    <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.5 }}>
      <Typography sx={{ fontSize: "0.7rem", color: "#64748B", fontFamily: "'DM Mono', monospace" }}>{label}</Typography>
      <Typography sx={{ fontSize: "0.7rem", color, fontFamily: "'DM Mono', monospace", fontWeight: 700 }}>{value}%</Typography>
    </Box>
    <Slider value={value} onChange={onChange} onChangeCommitted={onCommit} size="small"
      sx={{ color, "& .MuiSlider-track": { background: color } }} />
  </Box>
);

// ─── MAIN APP ─────────────────────────────────────────────────────────────────
function App() {
  const [data, setData]                           = useState(null);
  const [showPanel, setShowPanel]                 = useState(false);
  const [openDialog, setOpenDialog]               = useState(false);
  const [loadingRule, setLoadingRule]             = useState(null);
  const [selectedCode, setSelectedCode]           = useState("");
  const [openCode, setOpenCode]                   = useState(false);
  const [openEdit, setOpenEdit]                   = useState(false);
  const [selectedRule, setSelectedRule]           = useState(null);
  const [selectedColumns, setSelectedColumns]     = useState([]);
  const [weights, setWeights]                     = useState({ llm: 50, cosine: 30, fuzzy: 20 });
  const [execResult, setExecResult]               = useState(null);
  const [entityMappings, setEntityMappings]       = useState({});
  const [ruleTableMapping, setRuleTableMapping]   = useState({});
  const [openAddRule, setOpenAddRule]             = useState(false);
  const [newRule, setNewRule]                     = useState({ name: "", description: "", business_rule: "", complexity: "", category: "" });
  const [openAI, setOpenAI]                       = useState(false);
  const [aiRules, setAiRules]                     = useState([]);
  const [selectedAIRules, setSelectedAIRules]     = useState([]);
  const [selectedRuleDetail, setSelectedRuleDetail] = useState(null);
  const [snackbar, setSnackbar]                   = useState({ open: false, message: "", severity: "success" });
  const [globalLoading, setGlobalLoading]         = useState(false);
  const [loadingMeta, setLoadingMeta]             = useState({ message: "", subtext: "" });
  const [openRemediation, setOpenRemediation]     = useState(false);
  const [suggestions, setSuggestions]             = useState([]);
  const [selectedSuggestion, setSelectedSuggestion] = useState(null);
  const [canvasText, setCanvasText]               = useState("");
  const [remCode, setRemCode]                     = useState("");
  const [remResult, setRemResult]                 = useState(null);
  const [executedCount, setExecutedCount]         = useState(0);
  const [avgPassRate, setAvgPassRate]             = useState(0);
  const [exporting, setExporting]                 = useState(false);
  const [exportError, setExportError]             = useState("");
  const [runHistory, setRunHistory]               = useState([]);
  const [dashboardTab, setDashboardTab]           = useState("rules");
  const [allCodesReady, setAllCodesReady]         = useState(false);
  const [allCodesProgress, setAllCodesProgress]   = useState({ cached: 0, total: 0, failed: [] });
  const [rankedScores, setRankedScores]           = useState({});
  const [ragMode, setRagMode]                     = useState(false);
  const [ragLoading, setRagLoading]               = useState(false);
  const [chatOpen, setChatOpen]                   = useState(false);
  const [chatMessages, setChatMessages]           = useState([]);
  const [chatInput, setChatInput]                 = useState("");
  // Setter intentionally not destructured: nothing ever called setChatLoading, so this
  // is always false and the chat spinner is driven by ragLoading alone. Kept (rather
  // than deleted) because the three render sites below still read it.
  const [chatLoading]                             = useState(false);

  // schema_to_dataset : { schema_col: dataset_col }  — populated by /get_mappings
  const [schemaToDataset, setSchemaToDataset]     = useState({});
  const [hasSchema, setHasSchema]                 = useState(false);

  useEffect(() => {
    window.plugSDK.init({
      app_id: "DvRvStPZG9uOmNvcmU6ZHZydi11cy0xOmRldm8vMWVic000MmFDQzpwbHVnX3NldHRpbmcvMV9ffHxfXzIwMjYtMDQtMjMgMTA6MDU6NDIuNzE5OTQyNzg1ICswMDAwIFVUQw==xlxendsDvRv",
    });
  }, []);

  // Wraps setData so every new upload resets mapping state
  const handleSetData = (incoming) => {
    setSchemaToDataset({});
    setHasSchema(!!(incoming?.has_schema));
    setData(incoming);
  };

  const startLoading = (key) => { setLoadingMeta(LOADING_CONFIG[key]); setGlobalLoading(true); };
  const stopLoading  = ()    => setGlobalLoading(false);
  const notify = (message, severity = "success") => setSnackbar({ open: true, message, severity });

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleOpenAddRule = () => {
    if (!data) { notify("Upload a dataset first", "warning"); return; }
    setOpenAddRule(true);
  };

  const handleAddRule = async () => {
    if (!newRule.name || !newRule.business_rule) { notify("Name and Business Rule are required", "warning"); return; }
    startLoading("addRule");
    try {
      const enrichRes = await enrichedRuleAPI(newRule);
      const enrichedRule = {
        ...newRule,
        complexity: enrichRes.data.complexity,
        category:   enrichRes.data.category
      };
      setNewRule(enrichedRule);
      const res = await addRule(enrichedRule);
      setData({ ...data, rules: res.data.rules });
      setOpenAddRule(false);
      setNewRule({ name: "", description: "", business_rule: "", complexity: "", category: "" });
      notify("Rule added successfully");
    } catch { notify("Failed to add rule", "error"); }
    stopLoading();
  };

  const handleOpenAI = async () => {
    if (!data) { notify("Upload dataset first", "warning"); return; }
    startLoading("recommendRules");
    try {
      const res = await recommendRules();
      setAiRules(res.data.recommended_rules || []);
      setOpenAI(true);
    } catch { notify("Failed to fetch AI rules", "error"); }
    stopLoading();
  };

  const toggleSelectRule = (rule) =>
    setSelectedAIRules(prev => prev.includes(rule) ? prev.filter(r => r !== rule) : [...prev, rule]);

  const handleSaveAIRules = async () => {
    startLoading("saveAIRules");
    try {
      let res = {};
      for (const rule of selectedAIRules) res = await addRule(rule);
      setData({ ...data, rules: res.data.rules });
      setOpenAI(false);
      setSelectedAIRules([]);
      setSelectedRuleDetail(null);
      notify(`${selectedAIRules.length} rule(s) added`);
    } catch { notify("Failed to save rules", "error"); }
    stopLoading();
  };

  const handleCloseEdit = (_, reason) => {
    if (reason === "backdropClick" || reason === "escapeKeyDown") setOpenEdit(false);
  };

  // ── preloadMappings ────────────────────────────────────────────────────────
  // mapped_dict      = entity → schema_col   (values shown in chips + edit dropdown)
  // schema_to_dataset = schema_col → dataset_col  (stored for rename at code-gen time)
  const preloadMappings = async () => {
    if (!data?.rules) return;
    startLoading("preloadMap");
    try {
      const res = await getMappings(weights);
      const globalMapping       = res.data.mapped_dict       || {};  // entity → schema_col
      const globalRanked        = res.data.ranked_scores     || {};
      const globalRuleTableMap  = res.data.rule_table_map    || {};
      const s2d                 = res.data.schema_to_dataset || {};  // schema_col → dataset_col

      // Build per-rule entity → schema_col maps for the chip display
      const mappings = {};
      data.rules.forEach(rule => {
        const map = {};
        (rule.entities || []).forEach(entity => { map[entity] = globalMapping[entity]; });
        mappings[rule.name] = map;
      });

      setEntityMappings(mappings);
      setRankedScores(globalRanked);
      setRuleTableMapping(globalRuleTableMap);
      setSchemaToDataset(s2d);
    } catch { notify("Mapping failed", "error"); }
    stopLoading();
  };

  const handleViewCode = async (rule) => {
    setExecResult(null);
    setRemResult(null);
    setRemCode("");
    setSelectedRule(rule);
    setLoadingRule(rule.name);
    if (!allCodesReady) startLoading("generateCode");
    try {
      const res = await generateCode(rule, weights);
      setSelectedCode(res.data.pyspark_code);
      const maps = {};
      (rule.entities || []).forEach(name => { maps[name] = res.data.mapped_dict[name]; });
      setEntityMappings(prev => ({ ...prev, [rule.name]: maps }));
      // Keep schema_to_dataset in sync if backend returns an updated copy
      if (res.data.schema_to_dataset) setSchemaToDataset(res.data.schema_to_dataset);
      setOpenCode(true);
    } catch { notify("LLM is busy. Try again.", "error"); }
    setLoadingRule(null);
    if (!allCodesReady) stopLoading();
  };

  const handleExecute = async (rule) => {
    if (!rule?.name) { notify("Select a rule before execution", "warning"); return; }
    startLoading("executeCode");
    setExecResult(null);
    try {
      const res = await executeCode(selectedCode, rule.name);
      const isExecutionError = res.data?.status === "error";
      const result = isExecutionError ? { error: res.data?.error || "Execution failed" } : res.data?.result;
      setExecResult(result);
      setExecutedCount(res.data?.rules_executed ?? 0);
      setAvgPassRate(res.data?.avg_pass_rate ?? 0);

      if (!isExecutionError && result && !result.error) {
        setRunHistory(prev => [{
          run_id:    `RUN-${String(prev.length + 1).padStart(4, "0")}`,
          rule:      rule.name,
          passed:    result.passed_count ?? 0,
          failed:    result.failed_count ?? 0,
          pass_rate: result.pass_rate ?? 0,
          timestamp: new Date().toLocaleString("en-IN", {
            day: "2-digit", month: "short", year: "numeric",
            hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
          }),
        }, ...prev]);
      }
    } catch {
      setExecResult({ error: "Execution failed" });
    }
    stopLoading();
  };

  // handleEdit: populate dropdown with schema columns (mapped_dict values)
  // because user edits schema cols, not dataset cols
  const handleEdit = (rule) => {
    setSelectedRule(rule);
    const mapping = entityMappings[rule.name] || {};

    // mapped_dict values are schema cols — use those as initial selections
    const initialCols = (rule.entities || []).map(entity =>
      mapping[entity] || ""
    );
    setSelectedColumns(initialCols);
    setOpenEdit(true);
  };

  const handleWeightChange = async (newWeights) => {
    setWeights(newWeights);
    if (!selectedRule) return;
    startLoading("suggestCols");
    try {
      const res = await suggestColumns(selectedRule, newWeights);
      setSelectedColumns(res.data.suggested_columns);
    } catch { /* silent */ }
    stopLoading();
  };

  // handleRegenerate: selectedColumns are schema column names
  const handleRegenerate = async () => {
    setExecResult(null);
    setRemResult(null);
    setRemCode("");
    startLoading("regenerate");
    try {
      const res = await regenerateCode(selectedRule, selectedColumns, weights);
      setSelectedCode(res.data.pyspark_code);
      const matchings = {};
      (selectedRule.entities || []).forEach(col => { matchings[col] = res.data.mapped_dict[col]; });
      setEntityMappings(prev => ({ ...prev, [selectedRule.name]: matchings }));
      if (res.data.schema_to_dataset) setSchemaToDataset(res.data.schema_to_dataset);
      setOpenEdit(false);
      setOpenCode(true);
      notify("Code regenerated");
    } catch { notify("Failed to regenerate code", "error"); }
    stopLoading();
  };

  const handleRemediation = async (rule) => {
    startLoading("remediations");
    try {
      const res = await generateRemediation(rule, execResult?.failed_ids || [], execResult?.failed_count || 0);
      setSuggestions(res.data.suggestions);
      setOpenRemediation(true);
    } catch { notify("Failed to fetch remediation"); }
    stopLoading();
  };

  const handleGenerateRemCode = async () => {
    startLoading("remediationCode");
    const remediationPayload =
      selectedSuggestion?.logic === canvasText ? selectedSuggestion : null;
    const res = await generateRemediationCode(
      canvasText,
      execResult?.failed_ids || [],
      selectedRule,
      remediationPayload
    );
    setRemCode(res.data.pyspark_code);
    stopLoading();
  };

  const handleExecuteRem = async () => {
    startLoading("executeCode");
    const res = await executeRemediation(remCode, execResult?.failed_ids || [], canvasText);
    setRemResult(res.data);
    stopLoading();
  };

  const handleExport = async () => {
    if (!execResult?.failed_ids?.length) return;
    setExporting(true);
    setExportError("");
    try {
      await exportFailed(execResult.failed_ids, execResult.rule);
    } catch (err) {
      setExportError("Export failed. Please try again.");
    }
    setExporting(false);
  };

  const handleExportRemedies = async () => {
    setExporting(true);
    setExportError("");
    try {
      await exportFailedRemedies(execResult.rule);
    } catch (err) {
      setExportError("Export failed. Please try again.");
    }
    setExporting(false);
  };

  const handleGenerateAllCodes = async () => {
    startLoading("generateAll");
    setAllCodesReady(false);
    try {
      const res = await generateAllCodes(weights);
      if (res.data?.error) { notify(res.data.error, "error"); stopLoading(); return; }
      setAllCodesProgress({ cached: res.data.cached, total: res.data.total, failed: res.data.failed || [] });
      setAllCodesReady(true);
      const failCount = res.data.failed?.length ?? 0;
      if (failCount > 0) {
        notify(`${res.data.cached}/${res.data.total} rules generated. ${failCount} failed.`, "warning");
      } else {
        notify(`All ${res.data.cached} rules generated successfully`, "success");
      }
    } catch { notify("Failed to generate all codes", "error"); }
    stopLoading();
  };

  const handleRagQuery = async () => {
    if (!chatInput.trim() || ragLoading) return;
    const userMsg = { role: "user", content: chatInput, mode: "rag" };
    setChatMessages(prev => [...prev, userMsg]);
    setChatInput("");
    setRagLoading(true);
    try {
      const chatHistory = chatMessages
        .filter(m => m.role === "user" || m.role === "assistant")
        .map(m => ({ role: m.role, content: m.content }));
      const res = await ragQuery(chatInput, chatHistory);
      const answer = res.data.answer || "No answer found.";
      const sources = res.data.sources || [];
      const sourceText = sources.length > 0
        ? `\n\n📎 Sources: ${[...new Set(sources.map(s => s.type))].join(", ")}`
        : "";
      setChatMessages(prev => [...prev, {
        role: "assistant", content: answer + sourceText, mode: "rag", sources,
      }]);
    } catch {
      setChatMessages(prev => [...prev, {
        role: "assistant", content: "RAG query failed. Please try again.", mode: "rag"
      }]);
    }
    setRagLoading(false);
  };

  // ── Derived ───────────────────────────────────────────────────────────────
  const totalRules   = data?.rules?.length ?? 0;
  const totalColumns = data?.is_multi_table
    ? Object.values(data?.tables || {}).reduce((sum, t) => sum + t.columns.length, 0)
    : (data?.columns?.length ?? 0);
  const mappedRules    = Object.keys(entityMappings).length;
  const rulesConverted = executedCount;

  // Schema column list for edit dropdown (schema_to_dataset keys when schema present,
  // otherwise fall back to dataset columns)
  /*const schemaColOptions = hasSchema
    ? Object.keys(schemaToDataset)
    : (data?.is_multi_table
        ? Object.values(data?.tables || {}).flatMap(t => t.columns)
        : (data?.columns || []));*/
    // AFTER
  const schemaColOptions = hasSchema
      ? [...new Set(                          // deduplicate
          Object.entries(schemaToDataset)
              .filter(([schemaCol, datasetCol]) => !!datasetCol)  // only mapped ones
              .map(([schemaCol]) => schemaCol)
        )]
      : (data?.is_multi_table
          ? [...new Set(Object.values(data?.tables || {}).flatMap(t => t.columns))]
          : (data?.columns || []));

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <ThemeProvider theme={theme}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=DM+Mono:wght@400;500&display=swap');
        body { background:#080C14; margin:0; }
        ::-webkit-scrollbar { width:6px; }
        ::-webkit-scrollbar-track { background:#080C14; }
        ::-webkit-scrollbar-thumb { background:#1E2D45; border-radius:3px; }
        ::-webkit-scrollbar-thumb:hover { background:#00D4FF44; }
      `}</style>

      <GlobalLoader open={globalLoading} message={loadingMeta.message} subtext={loadingMeta.subtext} />

      <Box sx={{ minHeight: "100vh", background: "#080C14", pb: 8 }}>

        {/* ── Top Nav ── */}
        <Box sx={{
          borderBottom: "1px solid #1E2D45", background: "#0A1020",
          px: 4, py: 1.5,
          display: "flex", alignItems: "center", justifyContent: "space-between",
          position: "sticky", top: 0, zIndex: 100, backdropFilter: "blur(12px)",
        }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
            <Box sx={{
              width: 28, height: 28, borderRadius: 1,
              background: "linear-gradient(135deg, #00D4FF, #7C3AED)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <BarChartIcon sx={{ fontSize: 16, color: "#fff" }} />
            </Box>
            <Typography sx={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: "1rem", color: "#F1F5F9" }}>
              DataQuality<Box component="span" sx={{ color: "#00D4FF" }}>.engine</Box>
            </Typography>
          </Box>

          <Box sx={{ display: "flex", gap: 2, alignItems: "center" }}>
            {globalLoading && (
              <Box sx={{
                display: "flex", alignItems: "center", gap: 1,
                px: 1.5, py: 0.5,
                background: alpha("#00D4FF", 0.08),
                border: `1px solid ${alpha("#00D4FF", 0.2)}`,
                borderRadius: 1,
              }}>
                <Box sx={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: "#00D4FF",
                  animation: `${pulse} 1s ease-in-out infinite`,
                }} />
                <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.65rem", color: "#00D4FF" }}>
                  {loadingMeta.message}
                </Typography>
              </Box>
            )}
            <StatusDot active={!!data} />
            <Typography sx={{ fontSize: "0.7rem", color: "#475569", fontFamily: "'DM Mono', monospace" }}>
              {data ? "SESSION ACTIVE" : "NO SESSION"}
            </Typography>
          </Box>
        </Box>

        <Container maxWidth="lg" sx={{ pt: 5 }}>

          {/* ── Page Header ── */}
          <Box sx={{ mb: 5 }}>
            <Typography variant="h4" sx={{ color: "#F1F5F9", fontSize: { xs: "1.8rem", md: "2.4rem" } }}>
              Data Quality{" "}
              <Box component="span" sx={{
                background: "linear-gradient(90deg, #00D4FF, #7C3AED)",
                WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
              }}>
                Engine
              </Box>
            </Typography>
            <Typography sx={{ color: "#475569", mt: 1, fontFamily: "'DM Mono', monospace", fontSize: "0.8rem" }}>
              Automated PySpark rule generation · Entity mapping · Quality validation
            </Typography>
          </Box>

          {/* ── Stats Row ── */}
          {data && (
            <Box sx={{ display: "flex", gap: 2, mb: 4, flexWrap: "wrap" }}>
              <MetricBadge label={data?.is_multi_table ? "Total Cols" : "Columns"} value={totalColumns} color="#00D4FF" />
              {data?.is_multi_table && (
                <MetricBadge label="Tables" value={Object.keys(data?.tables || {}).length} color="#7C3AED" />
              )}
              <MetricBadge label="Rules"            value={totalRules}                         color="#7C3AED" />
              <MetricBadge label="Mapped"           value={mappedRules}                        color="#10B981" />
              <MetricBadge label="Average Pass Rate" value={execResult ? avgPassRate : "—"}    color="#F59E0B" />
              <MetricBadge label="Rules Executed"   value={rulesConverted}                     color="#FFA500" />
            </Box>
          )}

          {/* ── Upload Card ── */}
          <GlowCard sx={{ mb: 3 }}>
            <SectionLabel>Dataset Upload</SectionLabel>
            <Upload setData={(res) => {
              if (res.is_multi_table && res.tables) {
                const flatColumns = Object.values(res.tables).flatMap(t => t.columns);
                res.columns = flatColumns;
              }
              handleSetData(res);
              setShowPanel(true);
            }} />
          </GlowCard>

          {/* ── Action Bar ── */}
          <Box sx={{ display: "flex", gap: 2, mb: 3, flexWrap: "wrap" }}>
            <Button variant="outlined" startIcon={<AddIcon />} onClick={handleOpenAddRule} disabled={globalLoading} size="small">
              Add Rule
            </Button>
            <Button
              variant="outlined" startIcon={<AutoAwesomeIcon />} onClick={handleOpenAI}
              disabled={globalLoading} size="small"
              sx={{ borderColor: "#7C3AED44", color: "#A78BFA", "&:hover": { borderColor: "#7C3AED", color: "#C4B5FD", backgroundColor: alpha("#7C3AED", 0.05) } }}
            >
              AI Recommended Rules
            </Button>
          </Box>

          {/* ── Dataset Preview Panel ── */}
          <Slide in={showPanel} direction="up">
            <GlowCard>
              <Grid container spacing={3}>

                {/* Columns / Tables (only in rules tab) */}
                {dashboardTab === "rules" && (
                  <Grid item xs={12} md={5}>
                    {data?.is_multi_table ? (
                      <>
                        <SectionLabel>
                          <DatasetIcon sx={{ fontSize: 10, mr: 0.5 }} />
                          Tables ({Object.keys(data?.tables || {}).length}) · {totalColumns} columns
                        </SectionLabel>
                        <Box sx={{ display: "flex", flexDirection: "column", gap: 1.5, maxHeight: 220, overflowY: "auto" }}>
                          {Object.entries(data?.tables || {}).map(([tableName, { columns }]) => (
                            <Box key={tableName}>
                              <Box sx={{
                                px: 1.5, py: 0.5, mb: 0.75,
                                background: alpha("#7C3AED", 0.12), border: `1px solid ${alpha("#7C3AED", 0.25)}`,
                                borderRadius: 1, display: "flex", alignItems: "center", gap: 1,
                              }}>
                                <Box sx={{ width: 6, height: 6, borderRadius: "50%", background: "#7C3AED", flexShrink: 0 }} />
                                <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.7rem", color: "#A78BFA", fontWeight: 600 }}>
                                  {tableName}
                                </Typography>
                                <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.6rem", color: "#475569", ml: "auto" }}>
                                  {columns.length} cols
                                </Typography>
                              </Box>
                              <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, pl: 1 }}>
                                {columns.map((c, i) => (
                                  <Box key={i} sx={{
                                    px: 1.5, py: 0.3, background: "#111D2E", border: "1px solid #1E2D45",
                                    borderRadius: 1, fontFamily: "'DM Mono', monospace", fontSize: "0.65rem", color: "#94A3B8",
                                  }}>
                                    {c}
                                  </Box>
                                ))}
                              </Box>
                            </Box>
                          ))}
                        </Box>
                      </>
                    ) : (
                      <>
                        <SectionLabel>
                          <DatasetIcon sx={{ fontSize: 10, mr: 0.5 }} /> Dataset Columns ({totalColumns})
                        </SectionLabel>
                        <Box sx={{ maxHeight: 220, overflowY: "auto", display: "flex", flexWrap: "wrap", gap: 0.75 }}>
                          {data?.columns?.map((c, i) => (
                            <Box key={i} sx={{
                              px: 1.5, py: 0.4, background: "#111D2E", border: "1px solid #1E2D45",
                              borderRadius: 1, fontFamily: "'DM Mono', monospace", fontSize: "0.7rem", color: "#94A3B8",
                            }}>
                              {c}
                            </Box>
                          ))}
                        </Box>
                      </>
                    )}
                  </Grid>
                )}

                {/* Rules / Dashboard panel */}
                <Grid item xs={12} md={dashboardTab === "dashboard" ? 12 : 7}>

                  {/* Tab switcher */}
                  <Box sx={{ display: "flex", gap: 0, mb: 1.5, borderBottom: "1px solid #1E2D45" }}>
                    {[
                      { key: "rules",     label: `Active Rules (${totalRules})`,         icon: "◈" },
                      { key: "dashboard", label: `Run Dashboard (${runHistory.length})`, icon: "▦" },
                    ].map(tab => (
                      <Box key={tab.key} onClick={() => setDashboardTab(tab.key)} sx={{
                        px: 2, py: 1, cursor: "pointer",
                        fontFamily: "'DM Mono', monospace", fontSize: "0.65rem",
                        letterSpacing: "0.1em", textTransform: "uppercase",
                        color: dashboardTab === tab.key ? "#00D4FF" : "#475569",
                        borderBottom: dashboardTab === tab.key ? "2px solid #00D4FF" : "2px solid transparent",
                        transition: "all 0.15s", display: "flex", alignItems: "center", gap: 0.75,
                        "&:hover": { color: "#94A3B8" },
                      }}>
                        <Box component="span" sx={{ fontSize: "0.7rem" }}>{tab.icon}</Box>
                        {tab.label}
                      </Box>
                    ))}
                    {dashboardTab === "dashboard" && runHistory.length > 0 && (
                      <Box onClick={() => setRunHistory([])} sx={{
                        ml: "auto", px: 1.5, py: 1, cursor: "pointer",
                        fontFamily: "'DM Mono', monospace", fontSize: "0.6rem",
                        color: "#334155", "&:hover": { color: "#EF4444" }, transition: "color 0.15s",
                      }}>
                        ✕ clear
                      </Box>
                    )}
                  </Box>

                  {/* Rules tab */}
                  {dashboardTab === "rules" && (
                    <Box sx={{ display: "flex", flexDirection: "column", gap: 0.75, maxHeight: 220, overflowY: "auto" }}>
                      {data?.rules?.map((r, i) => (
                        <Box key={i} sx={{
                          display: "flex", alignItems: "center", gap: 1.5,
                          px: 1.5, py: 0.75, background: "#111D2E", border: "1px solid #1E2D45", borderRadius: 1,
                        }}>
                          <StatusDot active />
                          <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.75rem", color: "#CBD5E1", flex: 1 }}>
                            {r.name}
                          </Typography>
                          {r.category && (
                            <Box sx={{
                              px: 1, py: 0.2,
                              background: alpha("#7C3AED", 0.15), border: `1px solid ${alpha("#7C3AED", 0.3)}`,
                              borderRadius: 0.5, fontSize: "0.6rem", color: "#A78BFA", fontFamily: "'DM Mono', monospace",
                            }}>
                              {r.category}
                            </Box>
                          )}
                        </Box>
                      ))}
                    </Box>
                  )}

                  {/* Dashboard tab */}
                  {dashboardTab === "dashboard" && (
                    <Box sx={{ maxHeight: 260, overflowY: "auto" }}>
                      {runHistory.length === 0 ? (
                        <Box sx={{
                          display: "flex", flexDirection: "column", alignItems: "center",
                          justifyContent: "center", height: 180, gap: 1.5,
                        }}>
                          <Box sx={{
                            width: 36, height: 36, borderRadius: "50%",
                            background: alpha("#00D4FF", 0.06), border: `1px solid ${alpha("#00D4FF", 0.15)}`,
                            display: "flex", alignItems: "center", justifyContent: "center", fontSize: "1rem",
                          }}>▦</Box>
                          <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.7rem", color: "#334155" }}>
                            No runs yet — execute a rule to populate the dashboard
                          </Typography>
                        </Box>
                      ) : (
                        <Table size="small" stickyHeader>
                          <TableHead>
                            <TableRow>
                              {["Run ID", "Rule Executed", "Records Passed", "Records Failed", "Pass Rate", "Timestamp"].map(h => (
                                <TableCell key={h} sx={{
                                  backgroundColor: "#080C14", color: "#00D4FF",
                                  fontFamily: "'DM Mono', monospace", fontSize: "0.58rem",
                                  letterSpacing: "0.1em", textTransform: "uppercase",
                                  borderBottom: "1px solid #1E2D45", py: 1, px: 1.5, whiteSpace: "nowrap",
                                }}>{h}</TableCell>
                              ))}
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {runHistory.map((run, i) => (
                              <TableRow key={i} sx={{
                                "&:hover": { backgroundColor: "#111D2E" }, transition: "background 0.1s",
                                background: i === 0 ? alpha("#00D4FF", 0.03) : "transparent",
                              }}>
                                <TableCell sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.68rem", color: "#00D4FF", borderBottom: "1px solid #111D2E", py: 0.9, px: 1.5, whiteSpace: "nowrap" }}>
                                  <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                                    {i === 0 && <Box sx={{ width: 5, height: 5, borderRadius: "50%", background: "#10B981", boxShadow: "0 0 5px #10B981", flexShrink: 0 }} />}
                                    {run.run_id}
                                  </Box>
                                </TableCell>
                                <TableCell sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.68rem", color: "#CBD5E1", borderBottom: "1px solid #111D2E", py: 0.9, px: 1.5, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                  <Tooltip title={run.rule} placement="top"><span>{run.rule}</span></Tooltip>
                                </TableCell>
                                <TableCell sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.68rem", color: "#10B981", borderBottom: "1px solid #111D2E", py: 0.9, px: 1.5, whiteSpace: "nowrap" }}>
                                  {run.passed.toLocaleString()}
                                </TableCell>
                                <TableCell sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.68rem", color: run.failed > 0 ? "#EF4444" : "#475569", borderBottom: "1px solid #111D2E", py: 0.9, px: 1.5, whiteSpace: "nowrap" }}>
                                  {run.failed.toLocaleString()}
                                </TableCell>
                                <TableCell sx={{ borderBottom: "1px solid #111D2E", py: 0.9, px: 1.5 }}>
                                  <Box sx={{ display: "flex", alignItems: "center", gap: 1, minWidth: 100 }}>
                                    <Box sx={{ flex: 1, height: 3, borderRadius: 2, background: "#1E2D45", overflow: "hidden" }}>
                                      <Box sx={{
                                        width: `${Math.min((run.pass_rate * 100), 100).toFixed(1)}%`, height: "100%",
                                        background: run.pass_rate >= 0.9 ? "#10B981" : run.pass_rate >= 0.7 ? "#F59E0B" : "#EF4444",
                                        borderRadius: 2, transition: "width 0.4s ease",
                                      }} />
                                    </Box>
                                    <Typography sx={{
                                      fontFamily: "'DM Mono', monospace", fontSize: "0.65rem",
                                      color: run.pass_rate >= 0.9 ? "#10B981" : run.pass_rate >= 0.7 ? "#F59E0B" : "#EF4444",
                                      minWidth: 36, textAlign: "right",
                                    }}>
                                      {(run.pass_rate * 100).toFixed(1)}%
                                    </Typography>
                                  </Box>
                                </TableCell>
                                <TableCell sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.62rem", color: "#475569", borderBottom: "1px solid #111D2E", py: 0.9, px: 1.5, whiteSpace: "nowrap" }}>
                                  {run.timestamp}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      )}
                    </Box>
                  )}
                </Grid>
              </Grid>

              <Divider sx={{ borderColor: "#1E2D45", my: 3 }} />

              <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
                <Button variant="contained" startIcon={<CodeIcon />} disabled={globalLoading}
                  onClick={async () => { setOpenDialog(true); await preloadMappings(); }} sx={{ px: 3 }}>
                  Generate PySpark Queries
                </Button>
              </Box>
            </GlowCard>
          </Slide>
        </Container>
      </Box>

      {/* ══════════════════════════════════════════════════════════
          DIALOG: RULE TABLE
      ══════════════════════════════════════════════════════════ */}
      <Dialog open={openDialog} onClose={() => setOpenDialog(false)} fullWidth maxWidth="lg"
        PaperProps={{ sx: { maxHeight: "85vh" } }}>
        <DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #1E2D45", pb: 2 }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
            <CodeIcon sx={{ color: "#00D4FF", fontSize: 20 }} />
            <Typography variant="h6" sx={{ color: "#F1F5F9" }}>Rule Execution Console</Typography>
          </Box>
          <IconButton onClick={() => setOpenDialog(false)} size="small" sx={{ color: "#475569" }}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </DialogTitle>

        <DialogContent sx={{ p: 0 }}>
          <Table stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell width="25%">Rule Name</TableCell>
                <TableCell>Entity Mappings</TableCell>
                <TableCell width="240px" align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data?.rules?.map((rule, i) => {
                const mapping       = entityMappings[rule.name] || {};
                const ruleTables    = ruleTableMapping[rule.name] || {};
                const isMulti       = data?.is_multi_table;
                const hasMappings   = Object.keys(mapping).length > 0;
                const isThisLoading = loadingRule === rule.name;

                return (
                  <TableRow key={i}>
                    <TableCell>
                      <Box sx={{ display: "flex", flexDirection: "column", gap: 0.5 }}>
                        <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.8rem", color: "#E2E8F0" }}>
                          {rule.name}
                        </Typography>
                        {rule.complexity && (
                          <Box component="span" sx={{
                            fontSize: "0.6rem", fontFamily: "'DM Mono', monospace",
                            color: rule.complexity === "high" ? "#EF4444" : rule.complexity === "medium" ? "#F59E0B" : "#10B981",
                          }}>
                            ◆ {rule.complexity}
                          </Box>
                        )}
                      </Box>
                    </TableCell>

                    <TableCell>
                      {isThisLoading ? (
                        <InlineLoader label="generating mapping…" />
                      ) : !hasMappings ? (
                        <Typography sx={{ fontSize: "0.7rem", color: "#334155", fontFamily: "'DM Mono', monospace" }}>
                          — not generated
                        </Typography>
                      ) : (
                        <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
                          {isMulti && ruleTables && (
                            <Chip label={`Tables: ${ruleTables}`} size="small"
                              sx={{ alignSelf: "flex-start", background: "rgba(0,212,255,0.08)", color: "#00D4FF" }} />
                          )}
                          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.75 }}>
                            {Object.entries(mapping).map(([entity, schemaCol], idx) => {
                              // mapping now stores entity → schema_col
                              // schemaToDataset stores schema_col → dataset_col
                              const datasetCol = schemaToDataset[schemaCol];
                              const showChain  = hasSchema && datasetCol && datasetCol !== schemaCol;
                              return showChain ? (
                                // TWO-HOP: entity → schema_col → dataset_col
                                <Box key={idx} sx={{
                                  display: "flex", alignItems: "center", gap: 0.4,
                                  background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.2)",
                                  borderRadius: 1, px: 1, py: 0.3,
                                  fontSize: "0.65rem", fontFamily: "'DM Mono', monospace",
                                }}>
                                  <Typography component="span" sx={{ fontSize: "inherit", color: "#94A3B8" }}>{entity}</Typography>
                                  <Typography component="span" sx={{ fontSize: "inherit", color: "#475569" }}>→</Typography>
                                  <Typography component="span" sx={{ fontSize: "inherit", color: "#F59E0B", fontWeight: 700 }}>{schemaCol}</Typography>
                                  <Typography component="span" sx={{ fontSize: "inherit", color: "#475569" }}>→</Typography>
                                  <Typography component="span" sx={{ fontSize: "inherit", color: "#10B981", fontWeight: 700 }}>{datasetCol}</Typography>
                                </Box>
                              ) : (
                                // SINGLE-HOP or identity: entity → schema_col (== dataset_col)
                                <Chip key={idx} label={`${entity} → ${schemaCol}`} size="small" />
                              );
                            })}
                          </Box>
                          {hasSchema && Object.keys(mapping).some(e => schemaToDataset[mapping[e]] && schemaToDataset[mapping[e]] !== mapping[e]) && (
                            <Typography sx={{ fontSize: "0.58rem", fontFamily: "'DM Mono', monospace", color: "#475569", mt: 0.25 }}>
                              <span style={{ color: "#F59E0B" }}>■</span> schema col &nbsp;
                              <span style={{ color: "#10B981" }}>■</span> dataset col
                            </Typography>
                          )}
                        </Box>
                      )}
                    </TableCell>

                    <TableCell align="right">
                      <Box sx={{ display: "flex", gap: 1, justifyContent: "flex-end" }}>
                        <Tooltip title="Edit mapping">
                          <Button variant="outlined" size="small" onClick={() => handleEdit(rule)}
                            disabled={globalLoading} sx={{ minWidth: 0, px: 1.5 }}>
                            <EditIcon sx={{ fontSize: 14 }} />
                          </Button>
                        </Tooltip>
                        <Button
                          variant={isThisLoading ? "outlined" : "contained"} size="small"
                          onClick={() => handleViewCode(rule)}
                          disabled={isThisLoading || globalLoading}
                          startIcon={isThisLoading ? <CircularProgress size={12} color="inherit" /> : <CodeIcon sx={{ fontSize: 14 }} />}
                        >
                          {isThisLoading ? "Generating…" : "View Code"}
                        </Button>
                        <Tooltip title={!selectedCode ? "Generate code first" : "Execute rule"}>
                          <span>
                            <Button variant="outlined" size="small" onClick={handleExecute}
                              disabled={!selectedCode || globalLoading}
                              sx={{
                                minWidth: 0, px: 1.5,
                                borderColor: alpha("#10B981", 0.4), color: "#10B981",
                                "&:hover": { borderColor: "#10B981", backgroundColor: alpha("#10B981", 0.05) },
                                "&:disabled": { borderColor: "#1E2D45", color: "#334155" },
                              }}>
                              <PlayArrowIcon sx={{ fontSize: 14 }} />
                            </Button>
                          </span>
                        </Tooltip>
                      </Box>
                    </TableCell>
                  </TableRow>
                );
              })}
              {data && (
                <Button
                  variant="outlined" size="small"
                  startIcon={allCodesReady
                    ? <Box sx={{ width: 8, height: 8, borderRadius: "50%", background: "#10B981", boxShadow: "0 0 6px #10B981" }} />
                    : <CodeIcon sx={{ fontSize: 14 }} />}
                  onClick={handleGenerateAllCodes}
                  disabled={globalLoading}
                  sx={{
                    borderColor: allCodesReady ? alpha("#10B981", 0.4) : alpha("#00D4FF", 0.4),
                    color:       allCodesReady ? "#10B981" : "#00D4FF",
                    fontFamily: "'DM Mono', monospace", fontSize: "0.72rem",
                    "&:hover": {
                      borderColor: allCodesReady ? "#10B981" : "#00D4FF",
                      backgroundColor: allCodesReady ? alpha("#10B981", 0.05) : alpha("#00D4FF", 0.05),
                    },
                  }}
                >
                  {allCodesReady
                    ? `✓ All Queries Ready (${allCodesProgress.cached}/${allCodesProgress.total})`
                    : "Generate Queries for All Rules"}
                </Button>
              )}
            </TableBody>
          </Table>
        </DialogContent>
      </Dialog>

      {/* ══════════════════════════════════════════════════════════
          DIALOG: ADD RULE
      ══════════════════════════════════════════════════════════ */}
      <Dialog open={openAddRule} onClose={() => setOpenAddRule(false)} fullWidth maxWidth="sm">
        <DialogTitle sx={{ borderBottom: "1px solid #1E2D45", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            <AddIcon sx={{ color: "#00D4FF", fontSize: 18 }} />
            <Typography variant="h6" sx={{ color: "#F1F5F9" }}>Create Rule</Typography>
          </Box>
          <IconButton onClick={() => setOpenAddRule(false)} size="small" sx={{ color: "#475569" }}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </DialogTitle>
        <DialogContent sx={{ pt: 3 }}>
          {["name", "description", "business_rule"].map((field) => (
            <TextField key={field}
              label={field.replace("_", " ").replace(/\b\w/g, c => c.toUpperCase())}
              fullWidth margin="dense"
              value={newRule[field]}
              multiline={field === "business_rule"} rows={field === "business_rule" ? 3 : 1}
              disabled={globalLoading}
              onChange={(e) => setNewRule({ ...newRule, [field]: e.target.value })}
              InputLabelProps={{ sx: { color: "#475569", fontFamily: "'DM Mono', monospace", fontSize: "0.8rem" } }}
              InputProps={{ sx: { color: "#CBD5E1", fontFamily: "'DM Mono', monospace", fontSize: "0.85rem" } }}
            />
          ))}
          <Box mt={3} sx={{ display: "flex", justifyContent: "flex-end", gap: 1.5 }}>
            <Button variant="outlined" onClick={() => setOpenAddRule(false)} disabled={globalLoading}>Cancel</Button>
            <Button variant="contained" onClick={handleAddRule} disabled={globalLoading}>Save Rule</Button>
          </Box>
        </DialogContent>
      </Dialog>

      {/* ══════════════════════════════════════════════════════════
          DIALOG: AI RULES
      ══════════════════════════════════════════════════════════ */}
      <Dialog open={openAI} onClose={() => setOpenAI(false)} fullWidth maxWidth="md"
        PaperProps={{ sx: { maxHeight: "80vh" } }}>
        <DialogTitle sx={{ borderBottom: "1px solid #1E2D45", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            <AutoAwesomeIcon sx={{ color: "#A78BFA", fontSize: 18 }} />
            <Typography variant="h6" sx={{ color: "#F1F5F9" }}>AI Recommended Rules</Typography>
            <Box sx={{
              px: 1, py: 0.2, background: alpha("#7C3AED", 0.15), border: `1px solid ${alpha("#7C3AED", 0.3)}`,
              borderRadius: 0.5, fontSize: "0.65rem", color: "#A78BFA", fontFamily: "'DM Mono', monospace",
            }}>
              {aiRules.length} suggestions
            </Box>
          </Box>
          <IconButton onClick={() => setOpenAI(false)} size="small" sx={{ color: "#475569" }}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </DialogTitle>
        <DialogContent sx={{ p: 0 }}>
          <Grid container>
            <Grid item xs={5} sx={{ borderRight: "1px solid #1E2D45", overflowY: "auto", maxHeight: "60vh" }}>
              {aiRules.map((rule, i) => {
                const selected = selectedAIRules.includes(rule);
                const isDetail = selectedRuleDetail === rule;
                return (
                  <Box key={i} onClick={() => setSelectedRuleDetail(rule)} sx={{
                    display: "flex", alignItems: "center", gap: 1, px: 2, py: 1.5, cursor: "pointer",
                    borderBottom: "1px solid #111D2E",
                    background: isDetail ? alpha("#00D4FF", 0.06) : "transparent",
                    transition: "background 0.15s", "&:hover": { background: alpha("#00D4FF", 0.04) },
                  }}>
                    <Checkbox checked={selected} size="small"
                      onChange={(e) => { e.stopPropagation(); toggleSelectRule(rule); }}
                      sx={{ color: "#1E2D45", "&.Mui-checked": { color: "#7C3AED" }, p: 0.5 }} />
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.75rem", color: "#CBD5E1", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {rule.name}
                      </Typography>
                      {rule.category && (
                        <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.6rem", color: "#475569", mt: 0.25 }}>
                          {rule.category}
                        </Typography>
                      )}
                    </Box>
                    {isDetail && <Box sx={{ width: 3, height: 3, borderRadius: "50%", backgroundColor: "#00D4FF" }} />}
                  </Box>
                );
              })}
            </Grid>
            <Grid item xs={7} sx={{ p: 3, overflowY: "auto", maxHeight: "60vh" }}>
              {selectedRuleDetail ? (
                <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  {[["Name", selectedRuleDetail.name], ["Description", selectedRuleDetail.description],
                    ["Business Rule", selectedRuleDetail.business_rule], ["Complexity", selectedRuleDetail.complexity],
                    ["Category", selectedRuleDetail.category],
                  ].map(([label, value]) => value && (
                    <Box key={label}>
                      <SectionLabel>{label}</SectionLabel>
                      <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.8rem", color: "#94A3B8", lineHeight: 1.6 }}>
                        {value}
                      </Typography>
                    </Box>
                  ))}
                </Box>
              ) : (
                <Box sx={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", flexDirection: "column", gap: 1 }}>
                  <AutoAwesomeIcon sx={{ color: "#1E2D45", fontSize: 40 }} />
                  <Typography sx={{ color: "#334155", fontFamily: "'DM Mono', monospace", fontSize: "0.75rem" }}>
                    Select a rule to preview
                  </Typography>
                </Box>
              )}
            </Grid>
          </Grid>
        </DialogContent>
        <Box sx={{ p: 2, borderTop: "1px solid #1E2D45", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <Typography sx={{ fontSize: "0.7rem", color: "#475569", fontFamily: "'DM Mono', monospace" }}>
            {selectedAIRules.length} rule{selectedAIRules.length !== 1 ? "s" : ""} selected
          </Typography>
          <Box sx={{ display: "flex", gap: 1.5 }}>
            <Button variant="outlined" size="small" onClick={() => setOpenAI(false)} disabled={globalLoading}>Cancel</Button>
            <Button variant="contained" size="small" onClick={handleSaveAIRules}
              disabled={selectedAIRules.length === 0 || globalLoading}>
              Add Selected Rules
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* ══════════════════════════════════════════════════════════
          DIALOG: CODE VIEW
      ══════════════════════════════════════════════════════════ */}
      <Dialog open={openCode} onClose={() => setOpenCode(false)} fullWidth maxWidth="md"
        PaperProps={{ sx: { maxHeight: "90vh" } }}>
        <DialogTitle sx={{ borderBottom: "1px solid #1E2D45", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            <CodeIcon sx={{ color: "#00D4FF", fontSize: 18 }} />
            <Typography variant="h6" sx={{ color: "#F1F5F9" }}>Generated PySpark Code</Typography>
          </Box>
          <IconButton onClick={() => setOpenCode(false)} size="small" sx={{ color: "#475569" }}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </DialogTitle>
        <DialogContent sx={{ p: 0 }}>
          <Editor
            height="45vh" defaultLanguage="python"
            value={selectedCode.replace(/\\n/g, '\n') || "# No code generated yet"}
            onChange={(value) => setSelectedCode(value || "")}
            theme="vs-dark"
            options={{ fontSize: 13, minimap: { enabled: false }, wordWrap: "on", automaticLayout: true, scrollBeyondLastLine: false }}
          />
          <Box sx={{ px: 3, py: 2, borderBottom: "1px solid #1E2D45", display: "flex", alignItems: "center", gap: 2 }}>
            <Button variant="contained" startIcon={<PlayArrowIcon />}
              onClick={() => handleExecute(selectedRule)}
              disabled={!selectedCode || globalLoading}
              sx={{
                background: "linear-gradient(135deg, #10B981, #059669)",
                "&:hover": { background: "linear-gradient(135deg, #34D399, #10B981)" },
                "&:disabled": { background: "#1E2D45", color: "#334155" },
              }}>
              Execute
            </Button>
            <Typography sx={{ fontSize: "0.7rem", color: "#334155", fontFamily: "'DM Mono', monospace" }}>
              Runs against the uploaded dataset
            </Typography>
          </Box>
          {execResult && (
            <Box sx={{ px: 3, py: 2.5 }}>
              {execResult.error ? (
                <Box sx={{
                  display: "flex", alignItems: "flex-start", gap: 1.5, p: 2,
                  background: alpha("#EF4444", 0.08), border: `1px solid ${alpha("#EF4444", 0.25)}`, borderRadius: 1,
                }}>
                  <ErrorIcon sx={{ color: "#EF4444", fontSize: 18, mt: 0.1 }} />
                  <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.8rem", color: "#FCA5A5" }}>
                    {execResult.error}
                  </Typography>
                </Box>
              ) : (
                <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap" }}>
                    <MetricBadge label="Passed"    value={execResult.passed_count} color="#10B981" />
                    <MetricBadge label="Failed"    value={execResult.failed_count} color="#EF4444" />
                    <MetricBadge label="Pass Rate" value={execResult.pass_rate}    color="#F59E0B" />
                    {execResult.failed_count > 0 && (
                      <Box sx={{ ml: "auto" }}>
                        <Button onClick={() => handleRemediation(selectedRule)} variant="outlined" size="small"
                          startIcon={<Box sx={{ width: 14, height: 14, borderRadius: "50%", background: "linear-gradient(135deg, #F59E0B, #EF4444)", flexShrink: 0 }} />}
                          sx={{
                            borderColor: alpha("#F59E0B", 0.5), color: "#FCD34D",
                            fontFamily: "'DM Mono', monospace", fontSize: "0.72rem", fontWeight: 700,
                            letterSpacing: "0.06em", px: 2, py: 0.8, background: alpha("#F59E0B", 0.06),
                            "&:hover": { borderColor: "#F59E0B", background: alpha("#F59E0B", 0.12), color: "#FDE68A" },
                            position: "relative", overflow: "hidden",
                            "&::before": {
                              content: '""', position: "absolute", top: 0, left: "-100%",
                              width: "100%", height: "100%",
                              background: "linear-gradient(90deg, transparent, rgba(245,158,11,0.1), transparent)",
                              animation: `${pulse} 2s ease-in-out infinite`,
                            },
                          }}>
                          Remediation Engine
                        </Button>
                      </Box>
                    )}
                  </Box>
                  {execResult.failed_ids?.length > 0 && (
                    <Box>
                      <SectionLabel>Failed Record IDs</SectionLabel>
                      <Box sx={{
                        background: "#060A10", border: "1px solid #1E2D45", borderRadius: 1,
                        p: 2, fontFamily: "'DM Mono', monospace", fontSize: "0.75rem", color: "#94A3B8",
                        maxHeight: 140, overflowY: "auto", whiteSpace: "pre-wrap",
                      }}>
                        {JSON.stringify(execResult.failed_ids, null, 2)}
                      </Box>
                      <button onClick={handleExport} disabled={exporting} style={{
                        marginLeft: "auto", padding: "6px 18px",
                        backgroundColor: exporting ? "#ccc" : "#e53e3e",
                        color: "#fff", border: "none", borderRadius: 6,
                        cursor: exporting ? "not-allowed" : "pointer", fontWeight: 600, fontSize: 14,
                      }}>
                        {exporting ? "Exporting…" : `⬇ Export Failed Records (${execResult.failed_ids.length})`}
                      </button>
                    </Box>
                  )}
                </Box>
              )}
              {exportError && <p style={{ color: "red", margin: 0 }}>{exportError}</p>}
            </Box>
          )}
        </DialogContent>
      </Dialog>

      {/* ══════════════════════════════════════════════════════════
          DIALOG: EDIT MAPPING
          User edits SCHEMA columns (mapped_dict values).
          Dropdown options come from schemaColOptions (schema cols when schema
          is present, dataset cols when no schema).
      ══════════════════════════════════════════════════════════ */}
      <Dialog open={openEdit} onClose={handleCloseEdit} fullWidth maxWidth="sm">
        <DialogTitle sx={{ borderBottom: "1px solid #1E2D45", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
            <TuneIcon sx={{ color: "#00D4FF", fontSize: 18 }} />
            <Typography variant="h6" sx={{ color: "#F1F5F9" }}>Edit Mapping</Typography>
            {globalLoading && loadingMeta.message === LOADING_CONFIG.suggestCols.message && (
              <InlineLoader label="recalculating…" />
            )}
          </Box>
          <IconButton onClick={() => setOpenEdit(false)} size="small" sx={{ color: "#475569" }}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </DialogTitle>
        <DialogContent sx={{ pt: 3 }}>
          {selectedRule?.entities?.length > 0 && (
            <Box sx={{ mb: 3 }}>
              <SectionLabel>
                Entity → {hasSchema ? "Schema Column" : "Dataset Column"} Mapping
              </SectionLabel>
              {hasSchema && (
                <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.65rem", color: "#475569", mb: 1.5 }}>
                  Select the schema column for each entity. The dataset rename happens automatically.
                </Typography>
              )}
              {selectedRule.entities.map((entity, index) => {
                // rankedScores holds scores against schema cols (when schema present)
                const ranked = rankedScores[entity] || [];
                const top3   = ranked.slice(0, 3).map(([col]) => col);

                // Filter ranked list to schemaColOptions scope
                //let displayRanked = ranked.filter(([col]) => schemaColOptions.includes(col));
                let displayRanked        = ranked;
                let displaySchemaOptions = schemaColOptions;

                if (data?.is_multi_table && data?.tables) {
                  const involvedTables = ruleTableMapping[selectedRule?.name];
                  const tablesToShow   = (involvedTables && involvedTables.length > 0)
                      ? involvedTables
                      : Object.keys(data.tables);
                  const allowedDatasetCols = new Set(
                      tablesToShow.flatMap(t => data.tables[t]?.columns || [])
                  );

                  // Extract schema cols (keys) from schemaToDataset whose dataset col is in the involved tables
                  displaySchemaOptions = Object.entries(schemaToDataset)
                      .filter(([schemaCol, datasetCol]) => allowedDatasetCols.has(datasetCol))
                      .map(([schemaCol]) => schemaCol);

                  // Also filter ranked to only those schema cols
                  //displayRanked = ranked.filter(([col]) => displaySchemaOptions.includes(col));
                  // Deduplicate ranked scores — same col can appear multiple times
                  const seenCols = new Set();
                  displayRanked = ranked.filter(([col]) => {
                      if (seenCols.has(col)) return false;
                      seenCols.add(col);
                      return displaySchemaOptions.includes(col);
                  });
                }
                return (
                  <FormControl fullWidth sx={{ mt: 1.5 }} key={index} size="small">
                    <InputLabel sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.8rem", color: "#475569" }}>
                      {entity}
                    </InputLabel>
                    <Select
                      value={selectedColumns[index] || ""}
                      label={entity}
                      disabled={globalLoading}
                      onChange={(e) => {
                        const updated = [...selectedColumns];
                        updated[index] = e.target.value;
                        setSelectedColumns(updated);
                      }}
                      sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.8rem", color: "#CBD5E1" }}
                      renderValue={(val) => {
                        const entry  = displayRanked.find(([col]) => col === val);
                        const score  = entry ? entry[1] : null;
                        const isTop3 = top3.includes(val);
                        return (
                          <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                            <Typography sx={{
                              fontFamily: "'DM Mono', monospace", fontSize: "0.8rem",
                              color: "#CBD5E1", fontWeight: isTop3 ? 700 : 400,
                            }}>
                              {val}
                            </Typography>
                            {score !== null && (
                              <Box sx={{
                                px: 0.75, py: 0.1,
                                background: alpha(score >= 0.7 ? "#10B981" : score >= 0.4 ? "#F59E0B" : "#475569", 0.15),
                                border: `1px solid ${alpha(score >= 0.7 ? "#10B981" : score >= 0.4 ? "#F59E0B" : "#475569", 0.3)}`,
                                borderRadius: 0.5, fontSize: "0.58rem",
                                color: score >= 0.7 ? "#10B981" : score >= 0.4 ? "#F59E0B" : "#94A3B8",
                                fontFamily: "'DM Mono', monospace",
                              }}>
                                {(score * 100).toFixed(0)}%
                              </Box>
                            )}
                          </Box>
                        );
                      }}
                    >
                      {displayRanked.length === 0 ? (
                        schemaColOptions.map((col, i) => (
                          <MenuItem key={i} value={col} sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.8rem" }}>
                            {col}
                          </MenuItem>
                        ))
                      ) : (
                        displayRanked.map(([col, score], i) => {
                          const isTop3      = i < 3;
                          const scoreColor  = score >= 0.7 ? "#10B981" : score >= 0.4 ? "#F59E0B" : "#475569";
                          return (
                            <MenuItem key={i} value={col} sx={{
                              fontFamily: "'DM Mono', monospace", fontSize: "0.8rem",
                              display: "flex", alignItems: "center", justifyContent: "space-between", gap: 2, py: 0.9,
                              background: isTop3 ? alpha("#00D4FF", 0.03) : "transparent",
                              borderLeft: isTop3 ? `2px solid ${alpha("#00D4FF", 0.3)}` : "2px solid transparent",
                            }}>
                              <Box sx={{ display: "flex", alignItems: "center", gap: 1, flex: 1, minWidth: 0 }}>
                                <Box sx={{
                                  width: 16, height: 16, borderRadius: "50%", flexShrink: 0,
                                  display: "flex", alignItems: "center", justifyContent: "center",
                                  background: isTop3 ? alpha("#00D4FF", 0.12) : "transparent",
                                  border: isTop3 ? `1px solid ${alpha("#00D4FF", 0.25)}` : "none",
                                  fontSize: "0.5rem", color: isTop3 ? "#00D4FF" : "#334155", fontWeight: 700,
                                }}>
                                  {i + 1}
                                </Box>
                                <Typography sx={{
                                  fontFamily: "'DM Mono', monospace", fontSize: "0.78rem",
                                  fontWeight: isTop3 ? 700 : 400, color: isTop3 ? "#E2E8F0" : "#475569",
                                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                                }}>
                                  {col}
                                </Typography>
                              </Box>
                              <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexShrink: 0 }}>
                                <Box sx={{ width: 48, height: 3, borderRadius: 2, background: "#1E2D45", overflow: "hidden" }}>
                                  <Box sx={{ width: `${(score * 100).toFixed(0)}%`, height: "100%", background: scoreColor, borderRadius: 2 }} />
                                </Box>
                                <Typography sx={{
                                  fontFamily: "'DM Mono', monospace", fontSize: "0.65rem",
                                  color: scoreColor, minWidth: 30, textAlign: "right", fontWeight: isTop3 ? 700 : 400,
                                }}>
                                  {(score * 100).toFixed(0)}%
                                </Typography>
                              </Box>
                            </MenuItem>
                          );
                        })
                      )}
                    </Select>
                  </FormControl>
                );
              })}
            </Box>
          )}

          <Divider sx={{ borderColor: "#1E2D45", mb: 3 }} />
          <SectionLabel>Similarity Weights</SectionLabel>
          <WeightBar label="LLM Semantic"   value={weights.llm}    color="#00D4FF"
            onChange={(e, v) => setWeights({ ...weights, llm: v })}
            onCommit={(e, v) => handleWeightChange({ ...weights, llm: v })} />
          <WeightBar label="Cosine Distance" value={weights.cosine} color="#7C3AED"
            onChange={(e, v) => setWeights({ ...weights, cosine: v })}
            onCommit={(e, v) => handleWeightChange({ ...weights, cosine: v })} />
          <WeightBar label="Fuzzy Match"     value={weights.fuzzy}  color="#10B981"
            onChange={(e, v) => setWeights({ ...weights, fuzzy: v })}
            onCommit={(e, v) => handleWeightChange({ ...weights, fuzzy: v })} />

          <Box sx={{ display: "flex", justifyContent: "flex-end", gap: 1.5, mt: 3 }}>
            <Button variant="outlined" onClick={() => setOpenEdit(false)} disabled={globalLoading}>Cancel</Button>
            <Button variant="contained" onClick={handleRegenerate} disabled={globalLoading} startIcon={<CodeIcon />}>
              Regenerate & Save
            </Button>
          </Box>
        </DialogContent>
      </Dialog>

      {/* ══════════════════════════════════════════════════════════
          DIALOG: REMEDIATION ENGINE
      ══════════════════════════════════════════════════════════ */}
      <Dialog open={openRemediation} onClose={() => setOpenRemediation(false)} fullWidth maxWidth="lg"
        PaperProps={{ sx: { maxHeight: "90vh", background: "#0D1421", border: "1px solid #1E2D45" } }}>
        <DialogTitle sx={{ borderBottom: "1px solid #1E2D45", display: "flex", alignItems: "center", justifyContent: "space-between", pb: 2 }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
            <Box sx={{
              width: 10, height: 10, borderRadius: "50%",
              background: "linear-gradient(135deg, #F59E0B, #EF4444)",
              boxShadow: "0 0 10px rgba(245,158,11,0.5)",
              animation: `${pulse} 1.5s ease-in-out infinite`, flexShrink: 0,
            }} />
            <Typography variant="h6" sx={{ color: "#F1F5F9", fontFamily: "'Syne', sans-serif" }}>Remediation Engine</Typography>
            <Box sx={{
              px: 1.25, py: 0.25, background: alpha("#EF4444", 0.12), border: `1px solid ${alpha("#EF4444", 0.3)}`,
              borderRadius: 1, fontSize: "0.65rem", color: "#FCA5A5", fontFamily: "'DM Mono', monospace",
            }}>
              {execResult?.failed_count ?? 0} failed records
            </Box>
          </Box>
          <IconButton onClick={() => setOpenRemediation(false)} size="small" sx={{ color: "#475569" }}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </DialogTitle>
        <DialogContent sx={{ p: 0 }}>
          <Grid container sx={{ height: "100%", minHeight: 480 }}>

            {/* LEFT: Suggestions */}
            <Grid item xs={4} sx={{ borderRight: "1px solid #1E2D45", overflowY: "auto", maxHeight: "78vh" }}>
              <Box sx={{ px: 2, py: 1.5, borderBottom: "1px solid #1E2D45", background: "#080C14" }}>
                <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.62rem", letterSpacing: "0.14em", textTransform: "uppercase", color: "#475569" }}>
                  Suggested Actions
                </Typography>
              </Box>
              {suggestions.length === 0 ? (
                <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", py: 8, gap: 1.5 }}>
                  <Box sx={{
                    width: 36, height: 36, borderRadius: "50%",
                    background: alpha("#F59E0B", 0.08), border: `1px solid ${alpha("#F59E0B", 0.2)}`,
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    <Box sx={{ fontSize: "1rem" }}>⏳</Box>
                  </Box>
                  <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.7rem", color: "#334155" }}>
                    No suggestions yet
                  </Typography>
                </Box>
              ) : (
                suggestions.map((s, i) => {
                  const isSelected = selectedSuggestion === s;
                  return (
                    <Box key={i} onClick={() => { setSelectedSuggestion(s); setCanvasText(s.logic); }} sx={{
                      px: 2, py: 1.75, borderBottom: "1px solid #111D2E", cursor: "pointer",
                      background: isSelected ? alpha("#F59E0B", 0.07) : "transparent",
                      borderLeft: isSelected ? "3px solid #F59E0B" : "3px solid transparent",
                      transition: "all 0.15s", "&:hover": { background: alpha("#F59E0B", 0.04) },
                    }}>
                      <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1.25 }}>
                        <Box sx={{
                          width: 28, height: 28, borderRadius: 1, flexShrink: 0,
                          background: isSelected ? alpha("#F59E0B", 0.15) : "#111D2E",
                          border: `1px solid ${isSelected ? alpha("#F59E0B", 0.3) : "#1E2D45"}`,
                          display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.75rem",
                        }}>
                          {["🔧", "🔄", "🗑️", "✏️", "📋"][i % 5]}
                        </Box>
                        <Box sx={{ flex: 1, minWidth: 0 }}>
                          <Typography sx={{
                            fontFamily: "'DM Mono', monospace", fontSize: "0.75rem",
                            color: isSelected ? "#FCD34D" : "#CBD5E1", fontWeight: isSelected ? 600 : 400, lineHeight: 1.4,
                          }}>
                            {s.title}
                          </Typography>
                          {s.description && (
                            <Typography sx={{
                              fontFamily: "'DM Mono', monospace", fontSize: "0.62rem", color: "#475569", mt: 0.4,
                              overflow: "hidden", textOverflow: "ellipsis",
                              display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
                            }}>
                              {s.description}
                            </Typography>
                          )}
                        </Box>
                        {isSelected && <Box sx={{ width: 4, height: 4, borderRadius: "50%", background: "#F59E0B", mt: 0.5, flexShrink: 0 }} />}
                      </Box>
                    </Box>
                  );
                })
              )}
            </Grid>

            {/* RIGHT: Canvas + Code + Result */}
            <Grid item xs={8} sx={{ display: "flex", flexDirection: "column", overflowY: "auto", maxHeight: "78vh" }}>

              {/* 1. Logic editor */}
              <Box sx={{ px: 3, pt: 2.5, pb: 2, borderBottom: "1px solid #1E2D45" }}>
                <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1.25 }}>
                  <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.62rem", letterSpacing: "0.14em", textTransform: "uppercase", color: "#475569" }}>
                    Remediation Logic
                  </Typography>
                  {selectedSuggestion && (
                    <Box sx={{
                      px: 1, py: 0.2, background: alpha("#F59E0B", 0.1), border: `1px solid ${alpha("#F59E0B", 0.25)}`,
                      borderRadius: 0.5, fontSize: "0.6rem", color: "#FCD34D", fontFamily: "'DM Mono', monospace",
                    }}>
                      {selectedSuggestion.title}
                    </Box>
                  )}
                </Box>
                <TextField fullWidth multiline rows={5}
                  placeholder="Describe the remediation logic or select a suggestion from the left panel…"
                  value={canvasText} onChange={(e) => setCanvasText(e.target.value)}
                  InputProps={{ sx: {
                    fontFamily: "'DM Mono', monospace", fontSize: "0.8rem", color: "#CBD5E1", background: "#080C14",
                    "& fieldset": { borderColor: "#1E2D45" },
                    "&:hover fieldset": { borderColor: "#F59E0B" },
                    "&.Mui-focused fieldset": { borderColor: "#F59E0B" },
                  }}}
                />
                <Box sx={{ display: "flex", justifyContent: "flex-end", mt: 1.5 }}>
                  <Button onClick={handleGenerateRemCode} variant="contained" size="small" disabled={!canvasText.trim()}
                    sx={{
                      background: "linear-gradient(135deg, #F59E0B, #D97706)", color: "#080C14", fontWeight: 700,
                      fontFamily: "'DM Mono', monospace", fontSize: "0.75rem",
                      "&:hover": { background: "linear-gradient(135deg, #FCD34D, #F59E0B)" },
                      "&:disabled": { background: "#1E2D45", color: "#334155" },
                    }}>
                    ⚡ Generate Code
                  </Button>
                </Box>
              </Box>

              {/* 2. Generated code */}
              {remCode && (
                <Box sx={{ borderBottom: "1px solid #1E2D45" }}>
                  <Box sx={{ px: 3, py: 1.25, background: "#080C14", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.62rem", letterSpacing: "0.14em", textTransform: "uppercase", color: "#475569" }}>
                      Generated PySpark
                    </Typography>
                    <Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}>
                      <Box sx={{ width: 6, height: 6, borderRadius: "50%", background: "#10B981", boxShadow: "0 0 6px #10B981" }} />
                      <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.6rem", color: "#10B981" }}>ready</Typography>
                    </Box>
                  </Box>
                  <Editor height="180px" width="100%" defaultLanguage="python"
                    value={remCode || "# No remediation code generated"}
                    onChange={(value) => setRemCode(value || "")}
                    theme="vs-dark"
                    options={{ fontSize: 12, minimap: { enabled: false }, wordWrap: "on", scrollBeyondLastLine: false, automaticLayout: true }}
                  />
                  <Box sx={{ px: 3, py: 1.5, background: "#080C14" }}>
                    <Button onClick={handleExecuteRem} variant="contained" size="small" startIcon={<PlayArrowIcon sx={{ fontSize: 14 }} />}
                      sx={{
                        background: "linear-gradient(135deg, #10B981, #059669)", color: "#F1F5F9", fontWeight: 700,
                        fontFamily: "'DM Mono', monospace", fontSize: "0.75rem",
                        "&:hover": { background: "linear-gradient(135deg, #34D399, #10B981)" },
                      }}>
                      Take Action
                    </Button>
                    <Typography component="span" sx={{ ml: 2, fontFamily: "'DM Mono', monospace", fontSize: "0.65rem", color: "#334155" }}>
                      Applies changes to the dataset
                    </Typography>
                  </Box>
                </Box>
              )}

              {/* 3. Result */}
              {remResult && (
                <Box sx={{ px: 3, py: 2.5 }}>
                  <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.62rem", letterSpacing: "0.14em", textTransform: "uppercase", color: "#475569", mb: 2 }}>
                    Action Result
                  </Typography>
                  <Box sx={{
                    display: "inline-flex", flexDirection: "column", alignItems: "center",
                    px: 2.5, py: 1.5, mb: 2,
                    background: alpha("#10B981", 0.08), border: `1px solid ${alpha("#10B981", 0.25)}`, borderRadius: 1.5,
                  }}>
                    <Typography sx={{ fontSize: "1.6rem", fontWeight: 800, color: "#10B981", lineHeight: 1, fontFamily: "'Syne', sans-serif" }}>
                      {remResult.rows_affected}
                    </Typography>
                    <Typography sx={{ fontSize: "0.6rem", color: "#475569", mt: 0.5, letterSpacing: "0.1em", textTransform: "uppercase" }}>
                      rows affected
                    </Typography>
                  </Box>
                  {remResult.preview && remResult.preview.length > 0 && (
                    <Box sx={{ background: "#060A10", border: "1px solid #1E2D45", borderRadius: 1, overflow: "hidden" }}>
                      <Box sx={{ px: 2, py: 1, background: "#080C14", borderBottom: "1px solid #1E2D45" }}>
                        <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.62rem", color: "#475569", letterSpacing: "0.12em", textTransform: "uppercase" }}>
                          Preview
                        </Typography>
                      </Box>
                      <Box sx={{ overflowX: "auto", maxHeight: 180 }}>
                        <Table size="small">
                          <TableHead>
                            <TableRow>
                              {Object.keys(remResult.preview[0]).map((col, i) => (
                                <TableCell key={i} sx={{
                                  backgroundColor: "#080C14", color: "#10B981",
                                  fontFamily: "'DM Mono', monospace", fontSize: "0.6rem",
                                  letterSpacing: "0.1em", textTransform: "uppercase",
                                  borderBottom: "1px solid #1E2D45", whiteSpace: "nowrap", py: 1,
                                }}>{col}</TableCell>
                              ))}
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {remResult.preview.slice(0, 5).map((row, rowIdx) => (
                              <TableRow key={rowIdx}>
                                {Object.values(row).map((val, colIdx) => (
                                  <TableCell key={colIdx} sx={{
                                    fontFamily: "'DM Mono', monospace", fontSize: "0.72rem",
                                    color: "#94A3B8", borderBottom: "1px solid #111D2E", whiteSpace: "nowrap", py: 0.75,
                                  }}>
                                    {val === null || val === undefined
                                      ? <Box component="span" sx={{ color: "#334155", fontStyle: "italic" }}>null</Box>
                                      : String(val)}
                                  </TableCell>
                                ))}
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </Box>
                    </Box>
                  )}
                  <button onClick={handleExportRemedies} disabled={exporting} style={{
                    marginLeft: "auto", padding: "6px 18px",
                    backgroundColor: exporting ? "#ccc" : "#e53e3e",
                    color: "#fff", border: "none", borderRadius: 6,
                    cursor: exporting ? "not-allowed" : "pointer", fontWeight: 600, fontSize: 14,
                  }}>
                    {exporting ? "Exporting…" : `⬇ Export Failed Records (${execResult?.failed_ids?.length ?? 0})`}
                  </button>
                </Box>
              )}

              {/* Empty state */}
              {!remCode && !remResult && (
                <Box sx={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 2, py: 6 }}>
                  <Box sx={{
                    width: 48, height: 48, borderRadius: "50%",
                    background: alpha("#F59E0B", 0.08), border: `1px solid ${alpha("#F59E0B", 0.2)}`,
                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: "1.4rem",
                  }}>🔧</Box>
                  <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.75rem", color: "#334155", textAlign: "center" }}>
                    Select a suggestion or write remediation logic,<br />then generate code to take action.
                  </Typography>
                </Box>
              )}
            </Grid>
          </Grid>
        </DialogContent>
      </Dialog>

      {/* ── Snackbar ── */}
      <Snackbar open={snackbar.open} autoHideDuration={3500}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}>
        <Alert severity={snackbar.severity} onClose={() => setSnackbar({ ...snackbar, open: false })}
          sx={{ background: "#0D1421", border: "1px solid #1E2D45", fontFamily: "'DM Mono', monospace", fontSize: "0.8rem" }}>
          {snackbar.message}
        </Alert>
      </Snackbar>

      {/* ── Chat FAB ── */}
      {data && (
        <Box onClick={() => setChatOpen(o => !o)} sx={{
          position: "fixed", bottom: 28, right: 28, zIndex: 200,
          width: 52, height: 52, borderRadius: "50%",
          background: "linear-gradient(135deg, #00D4FF, #7C3AED)",
          display: "flex", alignItems: "center", justifyContent: "center",
          cursor: "pointer", boxShadow: "0 4px 24px rgba(0,212,255,0.35)",
          transition: "transform 0.2s", "&:hover": { transform: "scale(1.08)" },
        }}>
          <Typography sx={{ fontSize: "1.3rem" }}>{chatOpen ? "✕" : "💬"}</Typography>
        </Box>
      )}

      {/* ── Chat Panel ── */}
      {chatOpen && data && (
        <Box sx={{
         /* position: "fixed", bottom: 90, right: 28, zIndex: 200,
          width: 380, height: 520, borderRadius: 2,
          background: "#0D1421", border: "1px solid #1E2D45",
          boxShadow: "0 8px 40px rgba(0,0,0,0.6)",
          display: "flex", flexDirection: "column", overflow: "hidden",*/
        }}>
          {/* Header */}
          <Box sx={{ px: 2.5, py: 1.75, borderBottom: "1px solid #1E2D45", background: "#080C14", display: "flex", alignItems: "center", gap: 1.25 }}>
            <Box sx={{ width: 8, height: 8, borderRadius: "50%", background: "#10B981", boxShadow: "0 0 8px #10B981" }} />
            <Typography sx={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: "0.9rem", color: "#F1F5F9", flex: 1 }}>
              DQ Assistant
            </Typography>
            <Box sx={{ display: "flex", gap: 0, border: "1px solid #1E2D45", borderRadius: 1, overflow: "hidden" }}>
              {[{ key: false, label: "Agent" }, { key: true, label: "Ask Data" }].map(({ key, label }) => (
                <Box key={String(key)} onClick={() => setRagMode(key)} sx={{
                  px: 1.25, py: 0.4, cursor: "pointer",
                  fontFamily: "'DM Mono', monospace", fontSize: "0.6rem",
                  background: ragMode === key ? (key ? alpha("#7C3AED", 0.3) : alpha("#00D4FF", 0.2)) : "transparent",
                  color: ragMode === key ? (key ? "#C4B5FD" : "#00D4FF") : "#475569",
                  transition: "all 0.15s",
                }}>
                  {label}
                </Box>
              ))}
            </Box>
          </Box>

          {/* Messages */}
          <Box sx={{ flex: 1, overflowY: "auto", px: 2, py: 1.5, display: "flex", flexDirection: "column", gap: 1.25 }}>
            {chatMessages.length === 0 && (
              <Box sx={{ textAlign: "center", pt: 3 }}>
                <Typography sx={{ fontSize: "1.5rem", mb: 1 }}>{ragMode ? "🔍" : "🤖"}</Typography>
                <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.72rem", color: "#334155", lineHeight: 1.8 }}>
                  {ragMode ? (
                    <>
                      Ask anything about your <Box component="span" sx={{ color: "#A78BFA" }}>dataset</Box> or <Box component="span" sx={{ color: "#A78BFA" }}>rules</Box>.<br /><br />
                      <Box component="span" sx={{ color: "#7C3AED" }}>"What columns does the dataset have?"</Box><br />
                      <Box component="span" sx={{ color: "#7C3AED" }}>"What does rule 3 validate?"</Box><br />
                      <Box component="span" sx={{ color: "#7C3AED" }}>"Which rules check for null values?"</Box>
                    </>
                  ) : (
                    <>
                      I can <Box component="span" sx={{ color: "#00D4FF" }}>execute rules</Box>, <Box component="span" sx={{ color: "#00D4FF" }}>generate code</Box>, and more.<br /><br />
                      <Box component="span" sx={{ color: "#00D4FF" }}>"Run rule 3"</Box><br />
                      <Box component="span" sx={{ color: "#00D4FF" }}>"Execute all rules"</Box><br />
                      <Box component="span" sx={{ color: "#00D4FF" }}>"Export failed records"</Box>
                    </>
                  )}
                </Typography>
              </Box>
            )}
            {chatMessages.map((msg, i) => (
              <Box key={i} sx={{ display: "flex", justifyContent: msg.role === "user" ? "flex-end" : "flex-start" }}>
                <Box sx={{
                  maxWidth: "82%", px: 1.75, py: 1.1,
                  borderRadius: msg.role === "user" ? "12px 12px 2px 12px" : "12px 12px 12px 2px",
                  background: msg.role === "user"
                    ? (msg.mode === "rag" ? "linear-gradient(135deg, #7C3AED22, #A78BFA22)" : "linear-gradient(135deg, #00D4FF22, #7C3AED22)")
                    : "#111D2E",
                  border: `1px solid ${msg.role === "user"
                    ? (msg.mode === "rag" ? alpha("#7C3AED", 0.25) : alpha("#00D4FF", 0.25))
                    : "#1E2D45"}`,
                }}>
                  <Typography sx={{ fontFamily: "'DM Mono', monospace", fontSize: "0.77rem", color: msg.role === "user" ? "#E2E8F0" : "#CBD5E1", lineHeight: 1.65, whiteSpace: "pre-wrap" }}>
                    {msg.content}
                  </Typography>
                  {msg.mode === "rag" && msg.sources?.length > 0 && msg.role === "assistant" && (
                    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 1 }}>
                      {[...new Set(msg.sources.map(s => s.rule_name || s.type))].map((src, si) => (
                        <Box key={si} sx={{
                          px: 0.75, py: 0.15, borderRadius: 0.5,
                          background: alpha("#7C3AED", 0.15), border: `1px solid ${alpha("#7C3AED", 0.3)}`,
                          fontSize: "0.58rem", color: "#A78BFA", fontFamily: "'DM Mono', monospace",
                        }}>
                          {src}
                        </Box>
                      ))}
                    </Box>
                  )}
                </Box>
              </Box>
            ))}
            {(chatLoading || ragLoading) && (
              <Box sx={{ display: "flex", justifyContent: "flex-start" }}>
                <Box sx={{ px: 1.75, py: 1, background: "#111D2E", border: "1px solid #1E2D45", borderRadius: "12px 12px 12px 2px", display: "flex", gap: 0.5, alignItems: "center" }}>
                  {[0, 1, 2].map(d => (
                    <Box key={d} sx={{
                      width: 5, height: 5, borderRadius: "50%",
                      background: ragMode ? "#A78BFA" : "#00D4FF",
                      animation: `${pulse} 1.2s ease-in-out ${d * 0.2}s infinite`,
                    }} />
                  ))}
                </Box>
              </Box>
            )}
          </Box>

          {/* Input */}
          <Box sx={{ px: 2, py: 1.5, borderTop: "1px solid #1E2D45", background: "#080C14", display: "flex", gap: 1, alignItems: "flex-end" }}>
            <TextField fullWidth multiline maxRows={3} size="small"
              placeholder={ragMode ? "Ask about your data or rules…" : "Ask me to run, generate, export…"}
              value={chatInput} onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleRagQuery(); } }}
              disabled={chatLoading || ragLoading}
              InputProps={{ sx: {
                fontFamily: "'DM Mono', monospace", fontSize: "0.8rem", color: "#CBD5E1", background: "#0D1421",
                "& fieldset": { borderColor: ragMode ? alpha("#7C3AED", 0.4) : "#1E2D45" },
                "&:hover fieldset": { borderColor: ragMode ? "#7C3AED" : "#00D4FF" },
                "&.Mui-focused fieldset": { borderColor: ragMode ? "#7C3AED" : "#00D4FF" },
              }}}
            />
            <Button variant="contained" size="small" onClick={handleRagQuery}
              disabled={!chatInput.trim() || chatLoading || ragLoading}
              sx={{
                minWidth: 0, px: 1.5, py: 1,
                background: ragMode ? "linear-gradient(135deg, #7C3AED, #6D28D9)" : "linear-gradient(135deg, #00D4FF, #0099CC)",
                "&:disabled": { background: "#1E2D45", color: "#334155" },
              }}>
              ↑
            </Button>
          </Box>
        </Box>
      )}
    </ThemeProvider>
  );
}

export default App;

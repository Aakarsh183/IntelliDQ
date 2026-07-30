/*import React, { useState, useRef } from "react";
import { uploadFiles } from "../api";
import { Button, Typography, Box, CircularProgress, LinearProgress } from "@mui/material";
import { alpha } from "@mui/material/styles";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import TableChartIcon from "@mui/icons-material/TableChart";
import RuleIcon from "@mui/icons-material/Rule";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";

// ─── Shared tokens (mirrors App.js palette) ───────────────────────────────────
const CLR = {
  bg:       "#080C14",
  surface:  "#0D1421",
  border:   "#1E2D45",
  cyan:     "#00D4FF",
  violet:   "#7C3AED",
  green:    "#10B981",
  muted:    "#475569",
  text:     "#CBD5E1",
  mono:     "'DM Mono', 'Fira Code', monospace",
  syne:     "'Syne', sans-serif",
};

// ─── Drag-and-drop file zone ──────────────────────────────────────────────────
function FileZone({ label, icon: Icon, file, onFile, accept, accentColor }) {
  const inputRef  = useRef();
  const [dragging, setDragging] = useState(false);

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) onFile(f);
  };

  const fmt = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  };

  return (
    <Box
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      sx={{
        flex: 1,
        border: `1px dashed ${file ? alpha(accentColor, 0.5) : dragging ? accentColor : CLR.border}`,
        borderRadius: 2,
        p: 3,
        cursor: "pointer",
        background: file
          ? alpha(accentColor, 0.05)
          : dragging
          ? alpha(accentColor, 0.04)
          : "transparent",
        transition: "all 0.2s ease",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 1,
        minHeight: 160,
        position: "relative",
        "&:hover": {
          borderColor: alpha(accentColor, 0.6),
          background: alpha(accentColor, 0.04),
        },
      }}
    >
      <input
        ref={inputRef}
        hidden
        type="file"
        accept={accept}
        onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
      />

      { Icon }
      <Box sx={{
        width: 44, height: 44, borderRadius: 1.5,
        background: file ? alpha(accentColor, 0.15) : "#111D2E",
        border: `1px solid ${file ? alpha(accentColor, 0.3) : CLR.border}`,
        display: "flex", alignItems: "center", justifyContent: "center",
        transition: "all 0.2s",
      }}>
        {file
          ? <CheckCircleIcon sx={{ color: accentColor, fontSize: 22 }} />
          : <Icon sx={{ color: file ? accentColor : CLR.muted, fontSize: 22 }} />
        }
      </Box>

      { Label }
      <Typography sx={{
        fontFamily: CLR.syne,
        fontWeight: 600,
        fontSize: "0.8rem",
        color: file ? accentColor : CLR.text,
        textAlign: "center",
      }}>
        {label}
      </Typography>

      { File info or hint }
      {file ? (
        <Box sx={{ textAlign: "center" }}>
          <Typography sx={{
            fontFamily: CLR.mono, fontSize: "0.7rem",
            color: CLR.text,
            maxWidth: 180,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {file.name}
          </Typography>
          <Typography sx={{ fontFamily: CLR.mono, fontSize: "0.65rem", color: CLR.muted, mt: 0.25 }}>
            {fmt(file.size)}
          </Typography>
        </Box>
      ) : (
        <Typography sx={{ fontFamily: CLR.mono, fontSize: "0.65rem", color: CLR.muted, textAlign: "center" }}>
          Drop file or click to browse
        </Typography>
      )}

      { Accent corner glow when file loaded }
      {file && (
        <Box sx={{
          position: "absolute", top: 0, right: 0,
          width: 40, height: 40,
          background: `radial-gradient(circle at top right, ${alpha(accentColor, 0.25)}, transparent 70%)`,
          borderRadius: "0 8px 0 0",
          pointerEvents: "none",
        }} />
      )}
    </Box>
  );
}

// ─── Main Upload Component ────────────────────────────────────────────────────
function Upload({ setData }) {
  const [dataset,  setDataset]  = useState(null);
  const [rules,    setRules]    = useState(null);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState("");
  const [progress, setProgress] = useState(0);

  const handleUpload = async () => {
    if (!dataset || !rules) {
      setError("Both files are required to proceed.");
      return;
    }
    setError("");
    setLoading(true);
    setProgress(0);

    // Fake progress pulse while waiting
    const interval = setInterval(() => {
      setProgress(p => p < 85 ? p + Math.random() * 12 : p);
    }, 300);

    const formData = new FormData();
    formData.append("dataset", dataset);
    formData.append("rules",   rules);

    try {
      const res = await uploadFiles(formData);
      clearInterval(interval);

      if (res.data.error) {
        setError(res.data.error);
        setLoading(false);
        setProgress(0);
        return;
      }

      setProgress(100);
      localStorage.setItem("session_id", res.data.session_id);

      setTimeout(() => {
        setData(res.data);
        setLoading(false);
      }, 400);

    } catch (err) {
      clearInterval(interval);
      console.error(err);
      setError("Upload failed. Please check your files and try again.");
      setLoading(false);
      setProgress(0);
    }
  };

  const ready = dataset && rules;

  return (
    <Box>
      {Section label}
      <Typography sx={{
        fontFamily: CLR.mono,
        fontSize: "0.65rem",
        letterSpacing: "0.15em",
        textTransform: "uppercase",
        color: CLR.muted,
        mb: 2,
      }}>
        Source Files
      </Typography>

      { Drop zones }
      <Box sx={{ display: "flex", gap: 2, flexDirection: { xs: "column", sm: "row" } }}>
        <FileZone
          label="Dataset"
          icon={TableChartIcon}
          file={dataset}
          onFile={setDataset}
          accept=".csv,.xlsx,.parquet,.json"
          accentColor={CLR.cyan}
        />
        <FileZone
          label="Rules Config"
          icon={RuleIcon}
          file={rules}
          onFile={setRules}
          accept=".json,.yaml,.yml,.csv"
          accentColor={CLR.violet}
        />
      </Box>

      { Progress bar }
      {loading && (
        <Box sx={{ mt: 2.5 }}>
          <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.75 }}>
            <Typography sx={{ fontFamily: CLR.mono, fontSize: "0.65rem", color: CLR.muted }}>
              Uploading & parsing…
            </Typography>
            <Typography sx={{ fontFamily: CLR.mono, fontSize: "0.65rem", color: CLR.cyan }}>
              {Math.round(progress)}%
            </Typography>
          </Box>
          <LinearProgress
            variant="determinate"
            value={progress}
            sx={{
              height: 3,
              borderRadius: 2,
              backgroundColor: CLR.border,
              "& .MuiLinearProgress-bar": {
                background: `linear-gradient(90deg, ${CLR.cyan}, ${CLR.violet})`,
                borderRadius: 2,
              },
            }}
          />
        </Box>
      )}

      {Error message}
      {error && (
        <Box sx={{
          mt: 2,
          px: 2, py: 1.25,
          background: alpha("#EF4444", 0.07),
          border: `1px solid ${alpha("#EF4444", 0.25)}`,
          borderRadius: 1,
        }}>
          <Typography sx={{ fontFamily: CLR.mono, fontSize: "0.75rem", color: "#FCA5A5" }}>
            ⚠ {error}
          </Typography>
        </Box>
      )}

      { Upload button}
      <Box sx={{ mt: 2.5, display: "flex", alignItems: "center", gap: 2 }}>
        <Button
          variant="contained"
          onClick={handleUpload}
          disabled={loading || !ready}
          startIcon={loading
            ? <CircularProgress size={14} color="inherit" />
            : <CloudUploadIcon sx={{ fontSize: 16 }} />
          }
          sx={{
            px: 3, py: 1,
            fontFamily: CLR.mono,
            fontWeight: 700,
            fontSize: "0.8rem",
            background: ready && !loading
              ? `linear-gradient(135deg, ${CLR.cyan} 0%, #0099CC 100%)`
              : undefined,
            "&:disabled": {
              background: CLR.border,
              color: CLR.muted,
            },
          }}
        >
          {loading ? "Uploading…" : "Upload & Initialize"}
        </Button>

        {!ready && !loading && (
          <Typography sx={{ fontFamily: CLR.mono, fontSize: "0.65rem", color: CLR.muted }}>
            {!dataset && !rules ? "Select both files to continue"
              : !dataset ? "Dataset missing"
              : "Rules config missing"}
          </Typography>
        )}
      </Box>
    </Box>
  );
}

export default Upload;
*/
import React, { useState, useRef } from "react";
import { uploadFiles } from "../api";
import { Button, Typography, Box, CircularProgress, LinearProgress } from "@mui/material";
import { alpha } from "@mui/material/styles";
import TableChartIcon from "@mui/icons-material/TableChart";
import RuleIcon from "@mui/icons-material/Rule";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";

const CLR = {
  bg:      "#080C14",
  surface: "#0D1421",
  border:  "#1E2D45",
  cyan:    "#00D4FF",
  violet:  "#7C3AED",
  green:   "#10B981",
  amber:   "#F59E0B",
  muted:   "#475569",
  text:    "#CBD5E1",
  mono:    "'DM Mono', 'Fira Code', monospace",
  syne:    "'Syne', sans-serif",
};

// ─── Drag-and-drop file zone ──────────────────────────────────────────────────
function FileZone({ label, icon: Icon, file, onFile, accept, accentColor, optional }) {
  const inputRef  = useRef();
  const [dragging, setDragging] = useState(false);

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) onFile(f);
  };

  const fmt = (bytes) => {
    if (bytes < 1024)      return `${bytes} B`;
    if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  };

  return (
    <Box
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      sx={{
        flex: 1,
        border: `1px dashed ${file ? alpha(accentColor, 0.5) : dragging ? accentColor : CLR.border}`,
        borderRadius: 2,
        p: 3,
        cursor: "pointer",
        background: file ? alpha(accentColor, 0.05) : dragging ? alpha(accentColor, 0.04) : "transparent",
        transition: "all 0.2s ease",
        display: "flex", flexDirection: "column", alignItems: "center",
        justifyContent: "center", gap: 1, minHeight: 160,
        position: "relative",
        "&:hover": { borderColor: alpha(accentColor, 0.6), background: alpha(accentColor, 0.04) },
      }}
    >
      <input
        ref={inputRef} hidden type="file" accept={accept}
        onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
      />

      <Box sx={{
        width: 44, height: 44, borderRadius: 1.5,
        background: file ? alpha(accentColor, 0.15) : "#111D2E",
        border: `1px solid ${file ? alpha(accentColor, 0.3) : CLR.border}`,
        display: "flex", alignItems: "center", justifyContent: "center",
        transition: "all 0.2s",
      }}>
        {file
          ? <CheckCircleIcon sx={{ color: accentColor, fontSize: 22 }} />
          : <Icon sx={{ color: CLR.muted, fontSize: 22 }} />
        }
      </Box>

      <Typography sx={{
        fontFamily: CLR.syne, fontWeight: 600, fontSize: "0.8rem",
        color: file ? accentColor : CLR.text, textAlign: "center",
      }}>
        {label}
        {optional && !file && (
          <Typography component="span" sx={{ fontFamily: CLR.mono, fontSize: "0.6rem", color: CLR.muted, ml: 0.75 }}>
            optional
          </Typography>
        )}
      </Typography>

      {file ? (
        <Box sx={{ textAlign: "center" }}>
          <Typography sx={{
            fontFamily: CLR.mono, fontSize: "0.7rem", color: CLR.text,
            maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {file.name}
          </Typography>
          <Typography sx={{ fontFamily: CLR.mono, fontSize: "0.65rem", color: CLR.muted, mt: 0.25 }}>
            {fmt(file.size)}
          </Typography>
        </Box>
      ) : (
        <Typography sx={{ fontFamily: CLR.mono, fontSize: "0.65rem", color: CLR.muted, textAlign: "center" }}>
          Drop file or click to browse
        </Typography>
      )}

      {file && (
        <Box sx={{
          position: "absolute", top: 0, right: 0, width: 40, height: 40,
          background: `radial-gradient(circle at top right, ${alpha(accentColor, 0.25)}, transparent 70%)`,
          borderRadius: "0 8px 0 0", pointerEvents: "none",
        }} />
      )}
    </Box>
  );
}

// ─── Schema badge ─────────────────────────────────────────────────────────────
function SchemaBadge({ schemaFile }) {
  if (!schemaFile) return null;
  return (
    <Box sx={{
      mt: 1.5, px: 2, py: 1,
      display: "flex", alignItems: "center", gap: 1,
      background: alpha(CLR.amber, 0.07),
      border: `1px solid ${alpha(CLR.amber, 0.25)}`,
      borderRadius: 1,
    }}>
      <AccountTreeIcon sx={{ color: CLR.amber, fontSize: 14 }} />
      <Typography sx={{ fontFamily: CLR.mono, fontSize: "0.7rem", color: CLR.amber }}>
        Two-hop mapping enabled — entity → schema → dataset
      </Typography>
    </Box>
  );
}

// ─── Main Upload Component ────────────────────────────────────────────────────
function Upload({ setData }) {
  const [dataset, setDataset] = useState(null);
  const [rules,   setRules]   = useState(null);
  const [schema,  setSchema]  = useState(null);   // ← target schema JSON
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState("");
  const [progress, setProgress] = useState(0);

  const handleUpload = async () => {
    if (!dataset || !rules) {
      setError("Dataset and Rules files are required to proceed.");
      return;
    }
    setError("");
    setLoading(true);
    setProgress(0);

    const interval = setInterval(() => {
      setProgress(p => p < 85 ? p + Math.random() * 12 : p);
    }, 300);

    const formData = new FormData();
    formData.append("dataset", dataset);
    formData.append("rules",   rules);
    if (schema) formData.append("schema", schema);   // only when provided

    try {
      const res = await uploadFiles(formData);
      clearInterval(interval);

      if (res.data.error) {
        setError(res.data.error);
        setLoading(false);
        setProgress(0);
        return;
      }

      setProgress(100);
      localStorage.setItem("session_id", res.data.session_id);
      setTimeout(() => { setData(res.data); setLoading(false); }, 400);

    } catch (err) {
      clearInterval(interval);
      console.error(err);
      setError("Upload failed. Please check your files and try again.");
      setLoading(false);
      setProgress(0);
    }
  };

  const ready = dataset && rules;

  return (
    <Box>
      <Typography sx={{
        fontFamily: CLR.mono, fontSize: "0.65rem",
        letterSpacing: "0.15em", textTransform: "uppercase",
        color: CLR.muted, mb: 2,
      }}>
        Source Files
      </Typography>

      {/* Row 1: Dataset + Rules (required) */}
      <Box sx={{ display: "flex", gap: 2, flexDirection: { xs: "column", sm: "row" } }}>
        <FileZone
          label="Dataset" icon={TableChartIcon}
          file={dataset} onFile={setDataset}
          accept=".csv,.xlsx,.parquet,.json"
          accentColor={CLR.cyan}
        />
        <FileZone
          label="Rules Config" icon={RuleIcon}
          file={rules} onFile={setRules}
          accept=".json,.yaml,.yml,.csv,.xlsx"
          accentColor={CLR.violet}
        />
      </Box>

      {/* Row 2: Target Schema (optional) */}
      <Box sx={{ mt: 2 }}>
        <Typography sx={{
          fontFamily: CLR.mono, fontSize: "0.6rem",
          letterSpacing: "0.12em", textTransform: "uppercase",
          color: CLR.muted, mb: 1,
        }}>
          Target Schema{" "}
          <span style={{ color: CLR.amber }}>(optional — enables two-hop mapping)</span>
        </Typography>
        <FileZone
          label="Target Schema" icon={AccountTreeIcon}
          file={schema} onFile={setSchema}
          accept=".json"
          accentColor={CLR.amber}
          optional
        />
        <SchemaBadge schemaFile={schema} />
      </Box>

      {/* Progress bar */}
      {loading && (
        <Box sx={{ mt: 2.5 }}>
          <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.75 }}>
            <Typography sx={{ fontFamily: CLR.mono, fontSize: "0.65rem", color: CLR.muted }}>
              Uploading & parsing…
            </Typography>
            <Typography sx={{ fontFamily: CLR.mono, fontSize: "0.65rem", color: CLR.cyan }}>
              {Math.round(progress)}%
            </Typography>
          </Box>
          <LinearProgress
            variant="determinate" value={progress}
            sx={{
              height: 3, borderRadius: 2, backgroundColor: CLR.border,
              "& .MuiLinearProgress-bar": {
                background: `linear-gradient(90deg, ${CLR.cyan}, ${CLR.violet})`,
                borderRadius: 2,
              },
            }}
          />
        </Box>
      )}

      {/* Error */}
      {error && (
        <Box sx={{
          mt: 2, px: 2, py: 1.25,
          background: alpha("#EF4444", 0.07),
          border: `1px solid ${alpha("#EF4444", 0.25)}`,
          borderRadius: 1,
        }}>
          <Typography sx={{ fontFamily: CLR.mono, fontSize: "0.75rem", color: "#FCA5A5" }}>
            ⚠ {error}
          </Typography>
        </Box>
      )}

      {/* Upload button */}
      <Box sx={{ mt: 2.5, display: "flex", alignItems: "center", gap: 2 }}>
        <Button
          variant="contained" onClick={handleUpload}
          disabled={loading || !ready}
          startIcon={loading
            ? <CircularProgress size={14} color="inherit" />
            : <CloudUploadIcon sx={{ fontSize: 16 }} />
          }
          sx={{
            px: 3, py: 1, fontFamily: CLR.mono, fontWeight: 700, fontSize: "0.8rem",
            background: ready && !loading
              ? `linear-gradient(135deg, ${CLR.cyan} 0%, #0099CC 100%)` : undefined,
            "&:disabled": { background: CLR.border, color: CLR.muted },
          }}
        >
          {loading ? "Uploading…" : "Upload & Initialize"}
        </Button>

        {!ready && !loading && (
          <Typography sx={{ fontFamily: CLR.mono, fontSize: "0.65rem", color: CLR.muted }}>
            {!dataset && !rules ? "Select dataset and rules to continue"
              : !dataset ? "Dataset missing"
              : "Rules config missing"}
          </Typography>
        )}
      </Box>
    </Box>
  );
}

export default Upload;
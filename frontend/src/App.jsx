import { useEffect, useState, useCallback } from "react";

const API = import.meta.env.VITE_API ?? "http://localhost:8000";
// Seeded users: 1 = developer, 2 = reviewer (Figure 6 actor model).
const USERS = { developer: 1, reviewer: 2 };
const SEV = { High: "text-red-700 bg-red-50 border-red-300", Medium: "text-amber-700 bg-amber-50 border-amber-300" };
const DOT = { High: "bg-red-600", Medium: "bg-amber-500" };

export default function App() {
  const [role, setRole] = useState("reviewer");
  const [findings, setFindings] = useState([]);
  const [sel, setSel] = useState(null);
  const [detail, setDetail] = useState(null);
  const [audit, setAudit] = useState(null);
  const [repo, setRepo] = useState("");
  const [msg, setMsg] = useState("");
  const [feedback, setFeedback] = useState("");
  const [groups, setGroups] = useState([]);

  const call = useCallback(async (path, opts = {}, as = role) => {
    const r = await fetch(API + path, {
      ...opts,
      headers: { "Content-Type": "application/json", "X-User-Id": USERS[as], ...(opts.headers || {}) },
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || r.statusText);
    return body;
  }, [role]);

  const load = useCallback(() => {
    call("/findings/groups").then(setGroups).catch(() => {});
    return call("/findings").then(setFindings).catch(e => setMsg(e.message));
  }, [call]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    setAudit(null);
    if (sel) call(`/findings/${sel}`).then(setDetail).catch(e => setMsg(e.message));
    else setDetail(null);
  }, [sel, call]);

  const scan = () =>
    call("/scans", { method: "POST", body: JSON.stringify({ repo_path: repo }) }, "developer")
      .then(r => { setMsg(`Scan ${r.scan_id} complete: ${r.findings} findings`); load(); })
      .catch(e => setMsg(e.message));

  const decide = d =>
    call(`/findings/${sel}/decision`, { method: "POST", body: JSON.stringify({ decision: d, feedback }) }, "reviewer")
      .then(f => {
        setDetail(f); setFeedback("");
        setMsg(d === "approve" ? `Fix merged (${f.file_path})` : `Decision recorded: ${d}`);
        load();
      })
      .catch(e => setMsg(e.message));

  const showAudit = () => call(`/audit/${sel}`, {}, "developer").then(setAudit);

  const L = detail?.latest;
  const canDecide = role === "reviewer" && detail?.status === "awaiting_review";

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <header className="bg-[#1f3864] text-white px-5 py-3 flex items-center gap-4">
        <b className="text-lg">LegacyGuard</b>
        <input value={repo} onChange={e => setRepo(e.target.value)} placeholder="path to target git repository"
          className="flex-1 rounded px-2 py-1 text-sm text-slate-900" />
        <button onClick={scan} disabled={!repo}
          className="bg-white/20 hover:bg-white/30 rounded px-3 py-1 text-sm disabled:opacity-40">Trigger scan</button>
        <select value={role} onChange={e => setRole(e.target.value)} className="text-slate-900 rounded px-2 py-1 text-sm">
          <option value="reviewer">Reviewer</option>
          <option value="developer">Developer</option>
        </select>
      </header>
      {msg && <div className="bg-blue-50 border-b border-blue-200 px-5 py-2 text-sm">{msg}</div>}
      <div className="grid md:grid-cols-[22rem_1fr]">
        <aside className="border-r bg-white p-3 space-y-2 md:min-h-[calc(100vh-3rem)]">
          <h2 className="text-sm font-semibold text-slate-500">By root cause ({groups.length})</h2>
          {groups.map(g => (
            <div key={g.rule_id} className="rounded border border-slate-200 p-2 text-xs">
              <div className="font-semibold">{g.root_cause}</div>
              <div className="text-slate-500">{g.cwe_id} · {g.count} location{g.count > 1 ? "s" : ""} · {g.verified_fixes} verified fix{g.verified_fixes === 1 ? "" : "es"}</div>
            </div>
          ))}
          <h2 className="text-sm font-semibold text-slate-500 pt-2">All findings ({findings.length})</h2>
          {findings.map(f => (
            <button key={f.id} onClick={() => setSel(f.id)}
              className={`w-full text-left rounded border p-3 ${sel === f.id ? "border-blue-500 bg-blue-50" : "border-slate-200 hover:bg-slate-50"}`}>
              <div className="flex justify-between text-sm font-semibold">
                <span>{f.cwe_name.split(" (")[0]}</span>
                <span className="flex items-center gap-1"><i className={`w-2 h-2 rounded-full ${DOT[f.severity]}`} />{f.severity}</span>
              </div>
              <div className="text-xs text-slate-500">{f.file_path.split("/").pop()}:{f.line_number}</div>
              <div className="text-xs text-slate-400">{f.status.replace("_", " ")}</div>
            </button>
          ))}
          {!findings.length && <p className="text-sm text-slate-400">No findings yet. Trigger a scan.</p>}
        </aside>
        <main className="p-6 space-y-4">
          {!detail && <p className="text-slate-400">Select a finding to review.</p>}
          {detail && (
            <>
              <h1 className="text-xl font-bold">{detail.cwe_name} — {detail.file_path.split("/").pop()}:{detail.line_number}</h1>
              <div className="flex gap-2 text-xs">
                <span className={`border rounded px-2 py-0.5 ${SEV[detail.severity]}`}>{detail.cwe_id} — {detail.severity}</span>
                {L && L.popia_flag !== "none" && (
                  <span className="border rounded px-2 py-0.5 text-amber-800 bg-amber-50 border-amber-300">POPIA exposure: {L.popia_flag}</span>
                )}
              </div>
              {L ? (
                <>
                  <section>
                    <h3 className="font-semibold text-sm text-[#1f3864]">Why this matters</h3>
                    <p className="text-sm">{L.explanation}</p>
                  </section>
                  <section>
                    <h3 className="font-semibold text-sm text-[#1f3864]">
                      Proposed fix {L.branch && <span className="font-normal text-slate-500">(staged on branch {L.branch})</span>}
                    </h3>
                    <pre className="bg-slate-100 border rounded p-3 text-xs overflow-x-auto">
                      {L.patch_diff || "No safe automated fix was produced — human attention needed."}
                    </pre>
                  </section>
                  <section>
                    <h3 className="font-semibold text-sm text-[#1f3864]">Verification</h3>
                    <p className="text-sm flex items-center gap-2">
                      <i className={`w-3 h-3 rounded-full ${L.verification === "resolved" ? "bg-green-600" : "bg-red-600"}`} />
                      {L.verification === "resolved"
                        ? "Re-scan passed — finding no longer present on the staged branch."
                        : `Not verified (${L.verification}). Attempts used: ${detail.attempts.length}.`}
                    </p>
                  </section>
                </>
              ) : <p className="text-sm">No fix attempts recorded.</p>}
              {canDecide && (
                <div className="space-y-2">
                  <input value={feedback} onChange={e => setFeedback(e.target.value)}
                    placeholder="Optional feedback for Request Changes" className="w-full border rounded px-2 py-1 text-sm" />
                  <div className="flex gap-3">
                    <button disabled={L?.verification !== "resolved"} onClick={() => decide("approve")}
                      className="flex-1 border border-green-600 bg-green-50 text-green-800 font-semibold rounded py-2 disabled:opacity-40">Approve &amp; Merge</button>
                    <button onClick={() => decide("request_changes")}
                      className="flex-1 border border-amber-500 bg-amber-50 text-amber-800 font-semibold rounded py-2">Request Changes</button>
                    <button onClick={() => decide("reject")}
                      className="flex-1 border border-red-500 bg-red-50 text-red-800 font-semibold rounded py-2">Reject</button>
                  </div>
                </div>
              )}
              {role === "developer" && <p className="text-xs text-slate-500">Developers can scan and view the audit trail; switch to Reviewer to decide.</p>}
              {detail.status === "merged" && <p className="text-green-700 font-semibold">✓ Fix merged to main</p>}
              <button onClick={showAudit} className="text-sm text-blue-700 underline">View audit trail for this finding</button>
              {audit && (
                <ol className="border rounded bg-white p-3 text-sm space-y-1">
                  {audit.map(a => (
                    <li key={a.log_id}>
                      <span className="font-mono text-xs text-slate-500">{a.timestamp.slice(11, 19)}</span>{" "}
                      <b>{a.action.replace(/_/g, " ")}</b> — {a.detail} <span className="text-slate-400">({a.actor})</span>
                    </li>
                  ))}
                  <li className="text-xs italic text-slate-400">Entries are hash-chained and cannot be edited or deleted.</li>
                </ol>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}

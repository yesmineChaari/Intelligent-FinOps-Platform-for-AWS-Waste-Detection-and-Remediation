'use client';
import { useState, useEffect } from 'react';
import RunSelector from '@/components/engineer/RunSelector';
import Phase1Panel from '@/components/engineer/Phase1Panel';
import Phase2Panel from '@/components/engineer/Phase2Panel';
import LLMReportPanel from '@/components/engineer/LLMReportPanel';
import PRListPanel from '@/components/engineer/PRListPanel';
import AlertsPanel from '@/components/engineer/AlertsPanel';

type Tab = 'phase1' | 'phase2' | 'llm' | 'prs' | 'alerts';

const TABS: { id: Tab; label: string }[] = [
  { id: 'phase1',  label: 'Phase 1 — Detection' },
  { id: 'phase2',  label: 'Phase 2 — Guardrails' },
  { id: 'llm',     label: 'LLM Report' },
  { id: 'prs',     label: 'Pull Requests' },
  { id: 'alerts',  label: 'Alerts' },
];

interface PhaseData { ec2Phase1: any[]; s3Phase1: any[]; ec2Phase2: any[]; }
interface LLMData { ec2Waste: any[]; s3Waste: any[]; }

function Spinner() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-spin w-6 h-6 border-2 border-purple-500 border-t-transparent rounded-full" />
    </div>
  );
}

export default function EngineerInterface() {
  const [runs,          setRuns]          = useState<any[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [activeTab,     setActiveTab]     = useState<Tab>('phase1');
  const [phases,        setPhases]        = useState<PhaseData | null>(null);
  const [llmData,       setLlmData]       = useState<LLMData | null>(null);
  const [prs,           setPrs]           = useState<any[]>([]);
  const [prsError,      setPrsError]      = useState<string | undefined>();
  const [alerts,        setAlerts]        = useState<any[]>([]);
  const [alertsError,   setAlertsError]   = useState<string | undefined>();
  const [runsLoading,   setRunsLoading]   = useState(true);
  const [phaseLoading,  setPhaseLoading]  = useState(false);

  useEffect(() => {
    fetch('/api/runs')
      .then(r => r.json())
      .then(data => {
        const arr = Array.isArray(data) ? data : [];
        setRuns(arr);
        if (arr.length > 0) setSelectedRunId(arr[0].id);
      })
      .finally(() => setRunsLoading(false));

    fetch('/api/prs')
      .then(r => r.json())
      .then(data => {
        if (data?.error) setPrsError(data.error);
        else setPrs(Array.isArray(data) ? data : []);
      })
      .catch(e => setPrsError(String(e)));

    fetch('/api/alerts')
      .then(r => r.json())
      .then(data => {
        if (data?.error) setAlertsError(data.error);
        else setAlerts(Array.isArray(data) ? data : []);
      })
      .catch(e => setAlertsError(String(e)));
  }, []);

  useEffect(() => {
    if (!selectedRunId) return;
    setPhaseLoading(true);
    setPhases(null);
    setLlmData(null);
    Promise.all([
      fetch(`/api/phases/${selectedRunId}`).then(r => r.json()),
      fetch(`/api/llm/${selectedRunId}`).then(r => r.json()),
    ])
      .then(([phaseData, llm]) => { setPhases(phaseData); setLlmData(llm); })
      .finally(() => setPhaseLoading(false));
  }, [selectedRunId]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Engineer Interface</h1>
        <p className="text-gray-400 text-sm mt-1">
          Pipeline details, guardrail decisions, LLM analysis, infrastructure PRs, and alerts
        </p>
      </div>

      {runsLoading ? (
        <div className="flex items-center gap-2 text-gray-500 text-sm">
          <div className="animate-spin w-4 h-4 border-2 border-purple-500 border-t-transparent rounded-full" />
          Loading runs…
        </div>
      ) : (
        <RunSelector runs={runs} selectedId={selectedRunId} onChange={id => {
          setSelectedRunId(id);
          setActiveTab('phase1');
        }} />
      )}

      {!runsLoading && !runs.length && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center">
          <p className="text-gray-400">No optimization runs found</p>
          <p className="text-gray-600 text-xs mt-1">Run the pfa pipeline to generate data</p>
        </div>
      )}

      {selectedRunId && (
        <>
          <div className="flex gap-0 border-b border-gray-800">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-5 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
                  activeTab === tab.id
                    ? 'border-purple-500 text-purple-400'
                    : 'border-transparent text-gray-400 hover:text-white'
                }`}
              >
                {tab.label}
                {tab.id === 'prs' && prs.length > 0 && (
                  <span className="ml-1.5 px-1.5 py-0.5 rounded-full bg-purple-900 text-purple-300 text-xs">
                    {prs.length}
                  </span>
                )}
                {tab.id === 'alerts' && alerts.length > 0 && (
                  <span className="ml-1.5 px-1.5 py-0.5 rounded-full bg-red-900 text-red-300 text-xs">
                    {alerts.length}
                  </span>
                )}
              </button>
            ))}
          </div>

          {phaseLoading && activeTab !== 'prs' && activeTab !== 'alerts' ? (
            <Spinner />
          ) : (
            <>
              {activeTab === 'phase1' && phases && <Phase1Panel ec2={phases.ec2Phase1} s3={phases.s3Phase1} />}
              {activeTab === 'phase2' && phases && <Phase2Panel data={phases.ec2Phase2} />}
              {activeTab === 'llm' && llmData && <LLMReportPanel ec2Waste={llmData.ec2Waste} s3Waste={llmData.s3Waste} />}
              {activeTab === 'prs' && <PRListPanel prs={prs} error={prsError} />}
              {activeTab === 'alerts' && <AlertsPanel alerts={alerts} error={alertsError} />}
            </>
          )}
        </>
      )}
    </div>
  );
}

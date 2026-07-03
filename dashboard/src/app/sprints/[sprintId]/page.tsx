"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

export default function SprintDetail() {
  const { sprintId } = useParams<{sprintId: string}>();
  const [data, setData] = useState<any>(null);
  useEffect(() => {
    fetch(`/api/sprints/${sprintId}`).then(r => r.json()).then(setData);
  }, [sprintId]);
  if (!data) return <div className="p-6">Loading...</div>;
  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl">Sprint {sprintId}</h1>
      {["backlog","brief","engineering","grade","release","dora"].map(phase => {
        const env = data.envelopes?.[phase];
        return (
          <section key={phase}>
            <h2 className="text-lg font-bold">[{phase}]</h2>
            {env ? <pre className="text-xs bg-gray-50 p-3 whitespace-pre-wrap">
              {JSON.stringify(env, null, 2)}
            </pre> : <div className="text-gray-400 text-sm">no envelope</div>}
          </section>
        );
      })}
    </div>
  );
}

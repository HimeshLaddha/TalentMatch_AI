"use client";

import React from "react";

export default function SettingsPage() {
  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6">
      <div className="border-b border-tm-border pb-4">
        <h1 className="text-xl font-medium text-tm-text">Settings</h1>
        <p className="text-xs text-tm-muted mt-1">
          Configure matching thresholds, model endpoints, and evaluation preferences.
        </p>
      </div>

      <div className="border border-tm-border rounded-[12px] p-12 bg-tm-surface text-center">
        <div className="w-10 h-10 rounded-full bg-white border border-tm-border flex items-center justify-center mx-auto mb-4">
          <i className="ti ti-settings text-lg text-tm-text" />
        </div>
        <h3 className="text-sm font-medium text-tm-text">Application Settings</h3>
        <p className="text-xs text-tm-muted mt-1 max-w-sm mx-auto leading-relaxed">
          This section is currently under construction. In the future, you will be able to customize weighting formulas, token limits, and third-party integrations here.
        </p>
      </div>
    </div>
  );
}

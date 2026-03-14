"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ModuleGate } from "@/components/module-gate";

export default function SettingsPage() {
  return (
    <ModuleGate module="settings">
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Settings</h1>
      <Card>
        <CardHeader>
          <CardTitle>Account Settings</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Manage your account, preferences, and system configuration.
          </p>
        </CardContent>
      </Card>
    </div>
    </ModuleGate>
  );
}

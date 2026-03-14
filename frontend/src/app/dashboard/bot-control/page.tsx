"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ModuleGate } from "@/components/module-gate";

export default function BotControlPage() {
  return (
    <ModuleGate module="bot_control">
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Bot Control</h1>
      <Card>
        <CardHeader>
          <CardTitle>Trading Bots</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Start, stop, and configure automated trading bots here.
          </p>
        </CardContent>
      </Card>
    </div>
    </ModuleGate>
  );
}

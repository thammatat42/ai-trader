"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ModuleGate } from "@/components/module-gate";

export default function PlatformsPage() {
  return (
    <ModuleGate module="platforms">
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Platforms</h1>
      <Card>
        <CardHeader>
          <CardTitle>Trading Platforms</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Connect and manage trading platforms (MT5, Bitkub, Binance) here.
          </p>
        </CardContent>
      </Card>
    </div>
    </ModuleGate>
  );
}

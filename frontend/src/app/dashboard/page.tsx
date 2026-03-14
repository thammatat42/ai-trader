import { DollarSign, TrendingUp, Activity, BarChart3 } from "lucide-react";
import { StatCard } from "@/components/ui/stat-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Dashboard</h1>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Total Balance"
          value="$0.00"
          icon={DollarSign}
          description="Across all platforms"
        />
        <StatCard
          title="Today's P&L"
          value="$0.00"
          icon={TrendingUp}
          trend={{ value: 0, isPositive: true }}
        />
        <StatCard
          title="Open Positions"
          value="0"
          icon={Activity}
        />
        <StatCard
          title="Win Rate"
          value="0%"
          icon={BarChart3}
          description="Last 30 days"
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Recent Trades</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              No trades yet. Connect a platform to start trading.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>AI Analysis</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              No analysis available. Configure an AI provider to get started.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

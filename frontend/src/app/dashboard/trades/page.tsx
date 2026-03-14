import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function TradesPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Trades</h1>
      <Card>
        <CardHeader>
          <CardTitle>Trade History</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Trade history will appear here once platforms are connected.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

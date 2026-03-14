import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function LogsPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Logs</h1>
      <Card>
        <CardHeader>
          <CardTitle>System Logs</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            View bot events, audit logs, and AI analysis history here.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

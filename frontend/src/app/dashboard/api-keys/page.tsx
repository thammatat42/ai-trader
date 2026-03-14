import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function ApiKeysPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">API Keys</h1>
      <Card>
        <CardHeader>
          <CardTitle>Your API Keys</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Create and manage API keys for programmatic access.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function AiProvidersPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">AI Providers</h1>
      <Card>
        <CardHeader>
          <CardTitle>Configured Providers</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Add and manage AI providers (OpenRouter, NVIDIA NIM) here.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

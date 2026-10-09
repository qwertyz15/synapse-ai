import { AppProvider } from "@/components/app-provider";
import { AppSidebar } from "@/components/sidebar/app-sidebar";

export default function MainLayout({ children }: LayoutProps<"/">) {
  return (
    <AppProvider>
      <div className="flex h-dvh">
        <AppSidebar />
        <main className="relative flex min-w-0 flex-1 flex-col">{children}</main>
      </div>
    </AppProvider>
  );
}

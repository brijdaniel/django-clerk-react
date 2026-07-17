import { Heading } from "../ui/heading";
import Logger from "../utils/logger";

export function NotFound() {
    Logger.warn("Rendering NotFound page", { 
        component: "NotFound",
        data: { 
            path: window.location.pathname,
            url: window.location.href
        }
    });

    return (
        <main className="flex flex-1 flex-col w-screen h-screen">
            <div className="grow p-6 lg:bg-white lg:p-10 lg:shadow-sm lg:ring-1 lg:ring-zinc-950/5 dark:lg:bg-zinc-900 dark:lg:ring-white/10">
                <div className="mx-auto max-w-6xl text-brand-amber text-center">
                    <Heading className="text-2xl">Not Found!</Heading>
                </div>
            </div>
        </main>
    );
}

import { useEffect, useState } from "react";
import Logger from "../utils/logger";

export function useDebounce(value: string, delay: number) {
    const [debouncedValue, setDebouncedValue] = useState(value);

    useEffect(() => {
        Logger.debug("Setting up debounce timer", {
            component: "useDebounce",
            data: { value, delay }
        });

        const handler = setTimeout(() => {
            Logger.debug("Debounce timer completed", {
                component: "useDebounce",
                data: { value }
            });
            setDebouncedValue(value);
        }, delay);

        return () => {
            Logger.debug("Cleaning up debounce timer", {
                component: "useDebounce"
            });
            clearTimeout(handler);
        };
    }, [value, delay]);

    return debouncedValue;
}

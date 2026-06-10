/* Copyright 2026 Marimo. All rights reserved. */

import {
  AlertTriangleIcon,
  CheckIcon,
  PackageIcon,
  RefreshCwIcon,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip } from "@/components/ui/tooltip";
import { useAsyncData } from "@/hooks/useAsyncData";
import { useRequestClient } from "@/core/network/requests";
import type { CondaEnvironment } from "@/core/network/types";
import { cn } from "@/utils/cn";
import { Logger } from "@/utils/Logger";

/**
 * Conda environment picker shown in the notebook header.
 *
 * The picker is only meaningful when at least one conda-family env is
 * discovered on the machine; otherwise it stays hidden so non-conda users
 * see no UI clutter.
 *
 * Disambiguation: when two envs share a display name (e.g. two `base`
 * envs from a mambaforge + anaconda install), the dropdown shows the
 * full path on a second muted line.
 */
export const CondaEnvPicker: React.FC = () => {
  const { listCondaEnvironments, getNotebookCondaEnvironment, setNotebookCondaEnvironment } =
    useRequestClient();

  const envsData = useAsyncData(
    () => listCondaEnvironments().then((r) => r.environments),
    [],
  );
  const bindingData = useAsyncData(
    () =>
      getNotebookCondaEnvironment().then((r) => ({
        environment: r.environment,
      })),
    [],
  );

  const [pending, setPending] = useState(false);

  const envs = envsData.data ?? [];
  const declared = bindingData.data?.environment ?? null;

  const declaredEnvExists = useMemo(() => {
    if (!declared) {
      return true;
    }
    return envs.some((e) => e.name === declared);
  }, [envs, declared]);

  // The duplicate-name detection (e.g. two `base` envs from mambaforge +
  // anaconda) determines whether we render the path subtitle.
  const isDuplicateName = useCallback(
    (env: CondaEnvironment) => envs.filter((e) => e.name === env.name).length > 1,
    [envs],
  );

  // Hide the picker entirely when there are no conda envs on this
  // machine -- no point cluttering the header for uv/pip users.
  if (envsData.isPending && envs.length === 0) {
    return null;
  }
  if (envs.length === 0) {
    return null;
  }

  const onPick = async (name: string | null) => {
    setPending(true);
    try {
      const res = await setNotebookCondaEnvironment({ environment: name });
      if (!res.success) {
        Logger.error("Failed to update conda env binding:", res.error);
        return;
      }
      await bindingData.refetch();
    } catch (e) {
      Logger.error(e);
    } finally {
      setPending(false);
    }
  };

  const label = declared ?? "No env";
  const isWarning = declared !== null && !declaredEnvExists;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild={true}>
        <Button
          variant="outline"
          size="sm"
          data-testid="conda-env-picker"
          disabled={pending}
          className={cn(
            "h-7 px-2 text-xs font-mono",
            isWarning && "border-destructive text-destructive",
          )}
        >
          {isWarning ? (
            <AlertTriangleIcon className="w-3.5 h-3.5 mr-1.5" />
          ) : (
            <PackageIcon className="w-3.5 h-3.5 mr-1.5" />
          )}
          <span className="truncate max-w-[180px]">{label}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[260px] max-h-[400px] overflow-y-auto">
        <DropdownMenuLabel className="flex items-center justify-between">
          <span>Conda environment</span>
          <Tooltip content="Refresh env list">
            <button
              type="button"
              className="p-1 rounded hover:bg-muted"
              onClick={(e) => {
                e.preventDefault();
                envsData.refetch();
              }}
            >
              <RefreshCwIcon
                className={cn(
                  "w-3 h-3",
                  envsData.isPending && "animate-spin",
                )}
              />
            </button>
          </Tooltip>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {isWarning && (
          <div className="px-2 py-1.5 text-xs text-destructive">
            {`"${declared}" not found on this machine.`}
          </div>
        )}
        <DropdownMenuItem
          onSelect={() => onPick(null)}
          className="flex items-center justify-between"
        >
          <span className="text-muted-foreground">No env (system Python)</span>
          {declared === null && <CheckIcon className="w-3.5 h-3.5" />}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {envs.map((env) => {
          const isSelected = env.name === declared;
          return (
            <DropdownMenuItem
              key={env.path}
              onSelect={() => onPick(env.name)}
              className="flex flex-col items-start gap-0"
              data-testid={`conda-env-option-${env.name}`}
            >
              <div className="flex items-center justify-between w-full">
                <span className="font-mono text-sm">{env.name}</span>
                {isSelected && <CheckIcon className="w-3.5 h-3.5 ml-2" />}
              </div>
              {isDuplicateName(env) && (
                <span className="text-[10px] text-muted-foreground font-mono truncate max-w-[230px]">
                  {env.path}
                </span>
              )}
              {env.isActive && !isSelected && (
                <span className="text-[10px] text-muted-foreground italic">
                  currently active in the shell
                </span>
              )}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

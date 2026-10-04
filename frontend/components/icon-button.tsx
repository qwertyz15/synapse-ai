"use client";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

type Props = React.ComponentProps<typeof Button> & {
  label: string;
  side?: "top" | "bottom" | "left" | "right";
};

export function IconButton({ label, side = "bottom", children, ...props }: Props) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button variant="ghost" size="icon" aria-label={label} {...props}>
            {children}
          </Button>
        }
      />
      <TooltipContent side={side}>{label}</TooltipContent>
    </Tooltip>
  );
}

# Manual capability diagnostic failed

Lean could not synthesize the full conjunction decision instance. The compiler exited 1; its temporary sorryAx diagnostic is not an accepted proof. This manually assembled diagnostic was never supplied to training or target search. Raising maxSynthPendingDepth alone also failed; the bounded synthInstance.maxSize correction is tested separately.

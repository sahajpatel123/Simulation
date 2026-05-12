import { useMutation, useQueryClient, type UseMutationOptions } from '@tanstack/react-query'

type QueryKey = unknown[]

/**
 * A generic factory for creating React Query mutations with standard invalidation logic.
 */
export function useCeeMutation<TData, TError, TVariables, TContext>(
  mutationFn: (variables: TVariables) => Promise<TData>,
  invalidateKeys?: QueryKey[] | ((data: TData, variables: TVariables) => QueryKey[]),
  options?: Omit<UseMutationOptions<TData, TError, TVariables, TContext>, 'mutationFn'>
) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn,
    ...options,
    onSuccess: (...args) => {
      const [data, variables] = args
      if (invalidateKeys) {
        const keysToInvalidate =
          typeof invalidateKeys === 'function' ? invalidateKeys(data, variables) : invalidateKeys
        keysToInvalidate.forEach((key) => {
          queryClient.invalidateQueries({ queryKey: key })
        })
      }
      if (options?.onSuccess) {
        options.onSuccess(...args)
      }
    },
  })
}

import { useEffect, useState } from "react"

type ApiDataState<T> = {
  data: T | null
  isLoading: boolean
  error: string | null
}

export function useApiData<T>(loader: () => Promise<T>) {
  const [state, setState] = useState<ApiDataState<T>>({
    data: null,
    isLoading: true,
    error: null,
  })

  useEffect(() => {
    let isCurrent = true

    loader()
      .then((data) => {
        if (isCurrent) {
          setState({ data, isLoading: false, error: null })
        }
      })
      .catch(() => {
        if (isCurrent) {
          setState({
            data: null,
            isLoading: false,
            error: "Dashboard data could not be loaded.",
          })
        }
      })

    return () => {
      isCurrent = false
    }
  }, [loader])

  return state
}

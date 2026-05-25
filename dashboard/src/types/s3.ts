export type S3Finding = {
  bucket: string
  region: string
  issue: string
  storageClass: string
  footprint: string
  lifecycleAction: string
  estimatedSaving: number
  status: string
}

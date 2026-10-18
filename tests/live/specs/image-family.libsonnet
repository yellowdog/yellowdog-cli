// A run's Image Family for one provider: one group holding one image, the
// configured one, which the provider's Compute Source Template names. Every
// value is passed in as a variable reference, since the variables are
// substituted before Jsonnet evaluates the file.
function(name, provider, imageId, region) {
  resource: 'MachineImageFamily',
  namespace: '{{namespace}}',
  name: name,
  osType: 'LINUX',
  access: 'PRIVATE',
  imageGroups: [
    {
      name: 'images',
      osType: 'LINUX',
      images: [
        {
          name: 'image',
          provider: provider,
          providerImageId: imageId,
          osType: 'LINUX',
          regions: [region],
        },
      ],
    },
  ],
}

// Machine Image Families: three nested levels (family -> imageGroups ->
// images), each with its own metadata-shaped property (metadataSpecification
// on the family and group, metadata on the image), which is the shape most
// likely to be got wrong.
//
// The minimal variant carries only the family's own required properties and
// no imageGroups at all, proving nothing nested is secretly required. The
// maximal variant sets every other settable property at all three levels.
//
// The maximal variant carries TWO image groups deliberately, because that is a
// different code path rather than more of the same one. _create_image_family()
// can only send one group with the family itself, so it splits the list --
// imageGroups[:1] goes to add_image_family() and every remaining group is added
// afterwards, one call each, by add_image_group(). With a single group that loop
// never runs, so nothing exercised the split, the follow-up calls, or their
// error handling. The two groups also differ in their own
// metadataSpecification, which shows each group's specification being applied to
// its own images rather than the family's being applied to all of them.
//
// metadataSpecification is not merely descriptive: the platform rejects a
// family/group whose contained images' 'metadata' does not carry every
// key/value declared by every ancestor's metadataSpecification ("... must
// only contain machine images that meet the metadata specification defined
// for the machine image group/family"). This is a live-only finding (Task
// 8) -- the offline model-building path this corpus is otherwise checked
// against never performs this validation, so an image.metadata that omits
// an ancestor's required key/value builds a model cleanly offline and is
// only rejected by the real platform at creation time. The image's metadata
// below is therefore the union of the family's and the group's own
// metadataSpecification, not an independent value of its own.

local base = import 'lib/base.libsonnet';

local familyMin = {
  resource: 'MachineImageFamily',
  namespace: base.namespace,
  name: base.name('image-family-min'),
  osType: 'LINUX',
};

local familyMax = {
  resource: 'MachineImageFamily',
  namespace: base.namespace,
  name: base.name('image-family-max'),
  osType: 'LINUX',
  access: 'PRIVATE',
  metadataSpecification: { purpose: 'yd-cli-tests' },
  imageGroups: [
    // The first group is the one add_image_family() carries.
    {
      name: 'group-max',
      osType: 'LINUX',
      metadataSpecification: { level: 'group' },
      images: [
        {
          name: 'image-max',
          provider: 'AWS',
          providerImageId: '{{aws_image_id}}',
          osType: 'LINUX',
          regions: ['{{aws_region}}'],
          supportedInstanceTypes: ['{{aws_instance_type}}'],
          metadata: { purpose: 'yd-cli-tests', level: 'group' },
        },
      ],
    },
    // The second is added by a separate add_image_group() call, which is the
    // path this variant exists to reach. Its own metadataSpecification differs
    // from the first group's, so its image's metadata is the union of the
    // family's specification and *this* group's -- if the family's were applied
    // to every group instead, or a group's to its siblings, this image would be
    // rejected.
    {
      name: 'group-max-second',
      osType: 'LINUX',
      metadataSpecification: { level: 'second-group' },
      images: [
        {
          name: 'image-max-second',
          provider: 'GOOGLE',
          providerImageId: '{{gcp_image}}',
          osType: 'LINUX',
          regions: ['{{gcp_region}}'],
          supportedInstanceTypes: ['{{gcp_machine_type}}'],
          metadata: { purpose: 'yd-cli-tests', level: 'second-group' },
        },
      ],
    },
  ],
};

[familyMin, familyMax]

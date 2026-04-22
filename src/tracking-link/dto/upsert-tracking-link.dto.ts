import { Type } from 'class-transformer';
import { IsArray, IsString, ValidateNested } from 'class-validator';
import { SubscriberDto } from './subscriber.dto';

export class UpsertTrackingLinkDto {
  @IsString()
  trackingLinkId: string;

  @IsArray()
  @ValidateNested({ each: true })
  @Type(() => SubscriberDto)
  subscriptions: SubscriberDto[];
}

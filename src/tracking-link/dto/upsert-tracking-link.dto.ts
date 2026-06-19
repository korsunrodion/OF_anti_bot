import { ApiProperty } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import { IsArray, IsInt, IsString, ValidateNested } from 'class-validator';
import { SubscriberDto } from './subscriber.dto';

const SUBSCRIPTION_EXAMPLE = {
  id: '12345',
  username: 'john_doe',
  userId: 987654,
  subscriptionDate: '2024-06-01T12:00:00.000Z',
  avatarUrl: 'https://cdn.example.com/avatar.jpg',
  header: 'https://cdn.example.com/header.jpg',
  isOnlineMatchesSubscription: true,
  isReadingMessages: false,
  totalSpent: 1,
};
export class UpsertTrackingLinkDto {
  @ApiProperty({ example: 12345 })
  @Type(() => Number)
  @IsInt()
  trackingLinkId: number;

  @ApiProperty({ example: '@model_username' })
  @IsString()
  trackingLinkName: string;

  @ApiProperty({ type: [SubscriberDto], example: [SUBSCRIPTION_EXAMPLE] })
  @IsArray()
  @ValidateNested({ each: true })
  @Type(() => SubscriberDto)
  subscriptions: SubscriberDto[];
}
